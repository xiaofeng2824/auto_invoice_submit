from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from .config import resolve_path
from .record_store import append_records


@dataclass
class InvoiceParseResult:
    source_file: Path
    copied_file: Path | None
    order_id: str
    status: str
    message: str


def extract_pdf_text(pdf_path: Path) -> str:
    parts: list[str] = []
    with fitz.open(pdf_path) as document:
        for page in document:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def normalize_text(text: str) -> str:
    text = text.replace("：", ":")
    text = re.sub(r"[\t\r]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text


def extract_order_id(text: str, keywords: list[str], order_pattern: str) -> str | None:
    """Extract the Douyin order id from invoice text.

    Some electronic invoices place the order id as a standalone long number near
    the end of the text, after the item/tax/amount fields and before
    "下载次数". In that layout, choosing the longest number is wrong because the
    invoice number is usually longer than the order id. Prefer 19-digit numbers,
    which match the observed Douyin order id format.
    """
    normalized = normalize_text(text)
    keyword_pattern = "|".join(re.escape(keyword.replace("：", ":")) for keyword in keywords)

    # 1) 关键词命中：订单号: 6943321916273792285
    direct = re.search(
        rf"(?:{keyword_pattern})\s*[:：]?\s*({order_pattern})",
        normalized,
        flags=re.IGNORECASE,
    )
    if direct:
        return direct.group(1).strip(" _-:")

    # 2) 备注附近命中：适配 PDF 抽取成“备\n注\n...\n订单号”的情况。
    remark_match = re.search(r"备\s*注\s*[:：]?(.{0,500})", normalized, flags=re.DOTALL)
    if remark_match:
        remark_candidates = find_order_candidates(remark_match.group(1), order_pattern)
        if remark_candidates:
            return choose_best_order_candidate(remark_candidates)

    # 3) 全局兜底：优先 19 位数字，避免误取 20 位发票号码或金额拼接数字。
    candidates = find_order_candidates(normalized, order_pattern)
    if candidates:
        return choose_best_order_candidate(candidates)

    return None


def find_order_candidates(text: str, order_pattern: str) -> list[str]:
    candidates = re.findall(order_pattern, text)
    cleaned: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip(" _-:")
        if not has_digit(candidate):
            continue
        # 抖音订单号通常是较长纯数字；金额、税号、下载次数等短数字不作为候选。
        if candidate.isdigit() and len(candidate) < 15:
            continue
        cleaned.append(candidate)
    return cleaned


def has_digit(value: str) -> bool:
    return any(char.isdigit() for char in value)


def choose_best_order_candidate(candidates: list[str]) -> str:
    # 抖音订单号优先匹配 19 位纯数字。这样不会误取 20 位发票号码：26312000003585327961。
    numeric = [candidate for candidate in candidates if candidate.isdigit()]
    for length in (19, 18, 20):
        matched = [candidate for candidate in numeric if len(candidate) == length]
        if matched:
            # 同长度时取最后一个：电子发票文本里发票号码通常在前，备注/订单号通常在后。
            return matched[-1]
    if numeric:
        return numeric[-1]
    return max(candidates, key=len)


def sanitize_filename_part(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120] or "unknown"


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def copy_with_order_prefix(source: Path, output_dir: Path, order_id: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_order_id = sanitize_filename_part(order_id)
    destination = output_dir / f"{safe_order_id}_{source.name}"
    destination = unique_destination(destination)
    shutil.copy2(source, destination)
    return destination


def parse_single_pdf(pdf_path: Path, output_dir: Path, failed_dir: Path, keywords: list[str], order_pattern: str) -> InvoiceParseResult:
    try:
        text = extract_pdf_text(pdf_path)
    except Exception as exc:
        failed_dir.mkdir(parents=True, exist_ok=True)
        failed_copy = unique_destination(failed_dir / pdf_path.name)
        shutil.copy2(pdf_path, failed_copy)
        return InvoiceParseResult(pdf_path, failed_copy, "", "failed", f"PDF 读取失败: {exc}")

    order_id = extract_order_id(text, keywords, order_pattern)
    if not order_id:
        failed_dir.mkdir(parents=True, exist_ok=True)
        failed_copy = unique_destination(failed_dir / pdf_path.name)
        shutil.copy2(pdf_path, failed_copy)
        return InvoiceParseResult(pdf_path, failed_copy, "", "failed", "未识别到订单号")

    copied_file = copy_with_order_prefix(pdf_path, output_dir, order_id)
    return InvoiceParseResult(pdf_path, copied_file, order_id, "parsed", "已复制并添加订单号前缀")


def parse_invoices(config: dict[str, Any]) -> list[InvoiceParseResult]:
    input_dir = resolve_path(config["pdf"]["input_dir"])
    output_dir = resolve_path(config["pdf"]["output_dir"])
    failed_dir = resolve_path(config["pdf"]["failed_dir"])
    record_path = resolve_path(config["record"]["path"])
    keywords = config.get("invoice", {}).get("order_keywords", ["订单号"])
    order_pattern = config.get("invoice", {}).get("order_pattern", r"[A-Za-z0-9_-]{8,40}")

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    results: list[InvoiceParseResult] = []
    for pdf_path in sorted(input_dir.glob("*.pdf")):
        result = parse_single_pdf(pdf_path, output_dir, failed_dir, keywords, order_pattern)
        results.append(result)

    append_records(
        record_path,
        [
            {
                "source_file": str(result.source_file),
                "copied_file": str(result.copied_file or ""),
                "order_id": result.order_id,
                "status": result.status,
                "message": result.message,
                "uploaded": "no" if result.status == "parsed" else "",
            }
            for result in results
        ],
    )
    return results
