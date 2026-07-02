from __future__ import annotations

from pathlib import Path
import platform
import shutil
import time
from collections.abc import Callable
from typing import Any

from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import resolve_path
from .record_store import read_records, write_records


class OrderNotFoundError(Exception):
    """订单未搜索到，应跳过而非标记为失败。"""


def find_browser_executable() -> str | None:
    """Find an installed Chromium-based browser across common desktop systems."""
    system = platform.system()

    if system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Chromium\Application\chrome.exe",
            r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate

    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate

    command_candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "chromium",
        "chromium-browser",
        "msedge",
        "microsoft-edge",
    ]
    for command in command_candidates:
        found = shutil.which(command)
        if found:
            return found

    return None


class DouyinUploader:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.browser_config = config.get("browser", {})
        self.douyin_config = config.get("douyin", {})
        self.upload_config = config.get("upload", {})
        self.selectors = self.douyin_config.get("selectors", {})
        self.record_path = resolve_path(config["record"]["path"])
        self.storage_state_path = resolve_path(
            self.browser_config["storage_state_path"]
        )
        self.screenshot_dir = resolve_path(
            self.upload_config.get("screenshot_dir", "./data/screenshots")
        )

    def launch_browser(self, playwright, *, headless: bool):
        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "slow_mo": self.browser_config.get("slow_mo", 100),
        }
        executable_path = self.browser_config.get("executable_path", "auto")
        channel = self.browser_config.get("channel")

        if str(executable_path).strip().lower() == "auto":
            executable_path = find_browser_executable()

        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        elif channel:
            launch_kwargs["channel"] = channel

        return playwright.chromium.launch(**launch_kwargs)

    def login(self, wait_for_user: Callable[[], None] | None = None) -> None:
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = self.launch_browser(playwright, headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(
                self.browser_config.get("backend_url", "https://fxg.jinritemai.com/")
            )
            print(
                "请在打开的浏览器中完成抖音后台登录。登录完成并确认进入后台后，回到终端按 Enter 保存登录状态。"
            )
            if wait_for_user:
                wait_for_user()
            else:
                input()
            context.storage_state(path=str(self.storage_state_path))
            browser.close()
            print(f"登录状态已保存到: {self.storage_state_path}")

    def upload_from_records(
        self, wait_after_open: Callable[[], None] | None = None
    ) -> None:
        records = read_records(self.record_path)
        if not records:
            print(f"未找到台账记录: {self.record_path}")
            return

        targets = [
            record
            for record in records
            if record.get("status") == "parsed" and record.get("uploaded") != "yes"
        ]
        if not targets:
            print("没有需要上传的发票。")
            return

        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            browser = self.launch_browser(
                playwright,
                headless=self.browser_config.get("headless", False),
            )
            context_kwargs: dict[str, Any] = {}
            if self.storage_state_path.exists():
                context_kwargs["storage_state"] = str(self.storage_state_path)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.browser_config.get("timeout_ms", 30000000))

            self.open_invoice_page(page)
            if self.upload_config.get("pause_after_open", True):
                print(
                    "已打开后台页面。请确认页面已登录且位于发票管理相关页面，然后回到终端按 Enter 继续。"
                )
                if wait_after_open:
                    wait_after_open()
                else:
                    input()

            # 阶段1：依次提交所有发票，不进行中间校验
            print("\n=== 阶段1：依次提交发票（不校验）===")
            pending_verify: list[dict[str, str]] = []
            for record in targets:
                try:
                    self.submit_one(page, record)
                    pending_verify.append(record)
                    if self.upload_config.get("dry_run", True):
                        record["uploaded"] = "yes"
                        record["message"] = "dry_run：已完成筛选，未实际上传"
                    else:
                        record["uploaded"] = "submitted"
                        record["message"] = "已提交，待阶段2校验"
                except OrderNotFoundError:
                    record["uploaded"] = "skipped"
                    record["message"] = "未搜到对应订单"
                except Exception as exc:
                    record["uploaded"] = "failed"
                    record["message"] = f"提交失败: {exc}"
                    print(f"提交失败: {exc}")
                    self.safe_screenshot(page, record.get("order_id", "unknown"))
                finally:
                    write_records(self.record_path, records)

            # 阶段2：统一复搜校验，失败按 retry_count 重传再校验
            print(f"\n=== 阶段2：统一复搜校验（共 {len(pending_verify)} 条）===")
            for record in pending_verify:
                if record.get("uploaded") == "yes":
                    continue
                try:
                    self.verify_one(page, record)
                except Exception as exc:
                    record["uploaded"] = "failed"
                    record["message"] = f"校验失败: {exc}"
                    print(f"校验失败: {exc}")
                    self.safe_screenshot(page, record.get("order_id", "unknown"))
                finally:
                    write_records(self.record_path, records)

            context.storage_state(path=str(self.storage_state_path))
            browser.close()

    def open_invoice_page(self, page: Page) -> None:
        direct_url = self.douyin_config.get("invoice_management_url")
        page.goto(
            direct_url
            or self.browser_config.get("backend_url", "https://fxg.jinritemai.com/")
        )
        page.wait_for_load_state("domcontentloaded")
        if direct_url:
            return
        self.click_if_present(page, self.selectors.get("funds_menu"))
        self.click_if_present(page, self.selectors.get("invoice_menu"))
        self.click_if_present(page, self.selectors.get("pending_tab"))

    def submit_one(self, page: Page, record: dict[str, str]) -> None:
        """阶段1：先搜订单验证存在，再上传，不校验结果。"""
        order_id = record.get("order_id", "").strip()
        pdf_path = Path(record.get("copied_file", ""))
        if not order_id:
            raise ValueError("订单号为空")
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        print(f"提交订单: {order_id}")
        if not self.search_order(page, order_id):
            print(f"  [跳过] 未搜到订单 {order_id}")
            raise OrderNotFoundError(f"未搜到订单 {order_id}")

        if self.upload_config.get("dry_run", True):
            print(f"dry_run=true，跳过实际上传: {pdf_path}")
            return

        self._perform_upload(page, order_id, pdf_path)

    def verify_one(self, page: Page, record: dict[str, str]) -> None:
        """阶段2：复搜订单确认已离开待开票列表；失败则按 retry_count 重传并复搜。"""
        order_id = record.get("order_id", "").strip()
        pdf_path = Path(record.get("copied_file", ""))

        print(f"校验订单: {order_id}")
        max_attempts = self.upload_config.get("retry_count", 3)
        verify_delay = self.upload_config.get("verify_delay_ms", 3000)
        poll_interval = self.upload_config.get("verify_poll_interval_ms", 500)

        for attempt in range(1, max_attempts + 1):
            print(f"  第 {attempt}/{max_attempts} 次校验...")
            if self._poll_verify(page, order_id, verify_delay, poll_interval):
                print(f"  验证通过：订单 {order_id} 已不在待开票列表")
                record["uploaded"] = "yes"
                record["message"] = "上传成功"
                return
            if attempt < max_attempts:
                print(f"  订单仍在待开票列表，重传后再校验...")
                self._perform_upload(page, order_id, pdf_path)
            else:
                self.safe_screenshot(page, f"{order_id}_still_pending")
                raise RuntimeError(
                    f"上传失败：{max_attempts} 次尝试后订单 {order_id} 仍在待开票列表"
                )

    def _poll_verify(
        self, page: Page, order_id: str, budget_ms: int, interval_ms: int
    ) -> bool:
        """在 budget_ms 预算内每 interval_ms 复搜一次，订单消失即返回 True。"""
        deadline = time.monotonic() + budget_ms / 1000
        attempt = 0
        while time.monotonic() <= deadline:
            attempt += 1
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            print(f"  复搜验证 #{attempt}（剩余预算 {remaining}ms）...")
            if not self.search_order(page, order_id):
                return True
            if time.monotonic() <= deadline:
                page.wait_for_timeout(interval_ms)
        return False

    def _perform_upload(self, page: Page, order_id: str, pdf_path: Path) -> None:
        """执行一次完整的上传操作：点上传按钮→注入文件→提交→处理确认弹窗。"""

        # 第一步：主页面点击"上传发票"，弹出子页面/弹窗
        upload_button = self.selectors.get("upload_button", "text=上传发票")
        page.locator(upload_button).first.click()
        print("  已点击主页面上传发票按钮，等待子页面...")

        # 第二步：在子页面上找到隐藏的 <input type="file">，直接注入文件
        subpage_upload_btn = self.selectors.get(
            "subpage_upload_button", "text=上传发票"
        )
        subpage_upload_locator = page.locator(subpage_upload_btn).first
        subpage_upload_locator.wait_for(state="visible", timeout=10000)
        print("  子页面已出现")

        file_input_selector = self.selectors.get(
            "subpage_file_input", "input[type='file']"
        )
        file_input = page.locator(file_input_selector).first
        file_input.wait_for(state="attached", timeout=5000)
        file_input.set_input_files(str(pdf_path))
        print(f"  已注入文件: {pdf_path.name}")

        # 第三步：点击提交按钮
        subpage_submit_btn = self.selectors.get(
            "subpage_submit_button", "text=提交"
        )
        submit_locator = page.locator(subpage_submit_btn).first
        submit_locator.wait_for(state="visible", timeout=10000)
        submit_locator.click()
        print("  已点击提交按钮")

        # 第四步：处理确认弹窗
        # 先尝试拦截浏览器原生 dialog（alert/confirm）
        dialog_handled = False

        def handle_dialog(dialog):
            nonlocal dialog_handled
            print(f"  检测到浏览器原生弹窗: {dialog.message}")
            dialog.accept()
            dialog_handled = True

        page.on("dialog", handle_dialog)

        # 给弹窗一点渲染时间
        page.wait_for_timeout(1500)

        if not dialog_handled:
            # 等待确认按钮出现（给弹窗动画充足时间）
            confirm_selectors = [
                "button:has-text('确认')",
                "button:has-text('确定')",
                "button:has-text('提交')",
                "[class*='btn']:has-text('确认')",
                "[class*='btn']:has-text('确定')",
            ]
            confirm_btn = None
            for sel in confirm_selectors:
                try:
                    loc = page.locator(sel).last
                    loc.wait_for(state="visible", timeout=10000)
                    confirm_btn = loc
                    print(f"  找到确认按钮: {sel}")
                    break
                except PlaywrightTimeoutError:
                    continue

            if confirm_btn:
                try:
                    confirm_btn.click(timeout=5000)
                except Exception:
                    try:
                        confirm_btn.click(force=True)
                    except Exception:
                        confirm_btn.evaluate("el => el.click()")
                print("  已点击确认按钮")
                dialog_handled = True
            else:
                print("  未找到确认按钮，截图排查...")
                self.safe_screenshot(page, f"{order_id}_no_confirm_btn")

        if dialog_handled:
            page.wait_for_timeout(2000)
            print("  确认弹窗已处理")


    def search_order(self, page: Page, order_id: str) -> bool:
        """搜索订单，返回 True 表示找到结果，False 表示未找到。"""
        pending_tab = self.selectors.get("pending_tab")
        if pending_tab:
            self.click_if_present(page, pending_tab)

        order_input = self.selectors.get("order_input", "input[placeholder*='订单']")
        input_locator = page.locator(order_input).first
        input_locator.wait_for(state="visible")
        # 先清空再填入，避免残留上次搜索的内容
        input_locator.clear()
        input_locator.fill(order_id)

        search_button = self.selectors.get("search_button", "text=查询")
        page.locator(search_button).first.click()

        # 等搜索结果中出现当前订单号，比等"上传发票"更可靠
        # 因为页面默认列表里可能已经有"上传发票"按钮，会误命中旧数据
        try:
            page.wait_for_selector(f"text={order_id}", timeout=10000)
        except PlaywrightTimeoutError:
            return False
        page.wait_for_timeout(500)
        return True

    def click_if_present(self, page: Page, selector: str | None) -> bool:
        if not selector:
            return False
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=5000)
            locator.click()
            page.wait_for_timeout(500)
            return True
        except PlaywrightTimeoutError:
            return False

    def safe_screenshot(self, page: Page, order_id: str) -> None:
        try:
            safe_order = (
                "".join(char if char.isalnum() else "_" for char in order_id)
                or "unknown"
            )
            page.screenshot(
                path=str(self.screenshot_dir / f"{safe_order}.png"), full_page=True
            )
        except Exception:
            pass
