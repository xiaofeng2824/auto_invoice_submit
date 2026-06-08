from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import resolve_path
from .record_store import read_records, write_records


class DouyinUploader:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.browser_config = config.get("browser", {})
        self.douyin_config = config.get("douyin", {})
        self.upload_config = config.get("upload", {})
        self.selectors = self.douyin_config.get("selectors", {})
        self.record_path = resolve_path(config["record"]["path"])
        self.storage_state_path = resolve_path(self.browser_config["storage_state_path"])
        self.screenshot_dir = resolve_path(self.upload_config.get("screenshot_dir", "./data/screenshots"))

    def launch_browser(self, playwright, *, headless: bool):
        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "slow_mo": self.browser_config.get("slow_mo", 100),
        }
        executable_path = self.browser_config.get("executable_path")
        channel = self.browser_config.get("channel")
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        elif channel:
            launch_kwargs["channel"] = channel
        return playwright.chromium.launch(**launch_kwargs)

    def login(self) -> None:
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = self.launch_browser(playwright, headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(self.browser_config.get("backend_url", "https://fxg.jinritemai.com/"))
            print("请在打开的浏览器中完成抖音后台登录。登录完成并确认进入后台后，回到终端按 Enter 保存登录状态。")
            input()
            context.storage_state(path=str(self.storage_state_path))
            browser.close()
            print(f"登录状态已保存到: {self.storage_state_path}")

    def upload_from_records(self) -> None:
        records = read_records(self.record_path)
        if not records:
            print(f"未找到台账记录: {self.record_path}")
            return

        targets = [record for record in records if record.get("status") == "parsed" and record.get("uploaded") != "yes"]
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
            page.set_default_timeout(self.browser_config.get("timeout_ms", 30000))

            self.open_invoice_page(page)
            if self.upload_config.get("pause_after_open", True):
                print("已打开后台页面。请确认页面已登录且位于发票管理相关页面，然后回到终端按 Enter 继续。")
                input()

            for record in targets:
                try:
                    self.upload_one(page, record)
                    record["uploaded"] = "yes"
                    record["message"] = "上传成功" if not self.upload_config.get("dry_run", True) else "dry_run：已完成筛选，未实际上传"
                except Exception as exc:
                    record["uploaded"] = "failed"
                    record["message"] = f"上传失败: {exc}"
                    self.safe_screenshot(page, record.get("order_id", "unknown"))
                finally:
                    write_records(self.record_path, records)

            context.storage_state(path=str(self.storage_state_path))
            browser.close()

    def open_invoice_page(self, page: Page) -> None:
        direct_url = self.douyin_config.get("invoice_management_url")
        page.goto(direct_url or self.browser_config.get("backend_url", "https://fxg.jinritemai.com/"))
        page.wait_for_load_state("domcontentloaded")
        if direct_url:
            return
        self.click_if_present(page, self.selectors.get("funds_menu"))
        self.click_if_present(page, self.selectors.get("invoice_menu"))
        self.click_if_present(page, self.selectors.get("pending_tab"))

    def upload_one(self, page: Page, record: dict[str, str]) -> None:
        order_id = record.get("order_id", "").strip()
        pdf_path = Path(record.get("copied_file", ""))
        if not order_id:
            raise ValueError("订单号为空")
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        print(f"处理订单: {order_id}")
        self.search_order(page, order_id)

        if self.upload_config.get("dry_run", True):
            print(f"dry_run=true，跳过实际上传: {pdf_path}")
            return

        upload_button = self.selectors.get("upload_button", "text=上传发票")
        with page.expect_file_chooser() as chooser_info:
            page.locator(upload_button).first.click()
        chooser_info.value.set_files(str(pdf_path))

        confirm_button = self.selectors.get("confirm_button")
        if confirm_button:
            self.click_if_present(page, confirm_button)
        page.wait_for_load_state("networkidle")

    def search_order(self, page: Page, order_id: str) -> None:
        pending_tab = self.selectors.get("pending_tab")
        if pending_tab:
            self.click_if_present(page, pending_tab)

        order_input = self.selectors.get("order_input", "input[placeholder*='订单']")
        input_locator = page.locator(order_input).first
        input_locator.wait_for(state="visible")
        input_locator.fill(order_id)

        search_button = self.selectors.get("search_button", "text=查询")
        page.locator(search_button).first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

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
            safe_order = "".join(char if char.isalnum() else "_" for char in order_id) or "unknown"
            page.screenshot(path=str(self.screenshot_dir / f"{safe_order}.png"), full_page=True)
        except Exception:
            pass
