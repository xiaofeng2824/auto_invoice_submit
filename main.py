from __future__ import annotations

import argparse
from pathlib import Path

from src.config import load_config
from src.douyin_uploader import DouyinUploader
from src.invoice_parser import parse_invoices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发票 PDF 订单号提取、复制重命名与抖音后台上传工具")
    parser.add_argument(
        "command",
        choices=["parse", "login", "upload", "run"],
        help="parse=解析并复制 PDF；login=保存抖音登录态；upload=上传台账中的发票；run=parse+upload",
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径，默认 config.yaml")
    return parser


def print_parse_summary(results) -> None:
    total = len(results)
    success = sum(1 for result in results if result.status == "parsed")
    failed = total - success
    print(f"处理完成：共 {total} 个 PDF，成功 {success} 个，失败 {failed} 个。")
    for result in results:
        target = result.copied_file if result.copied_file else ""
        print(f"[{result.status}] {Path(result.source_file).name} -> {target} {result.message}")


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)

    if args.command == "parse":
        print_parse_summary(parse_invoices(config))
        return

    if args.command == "login":
        DouyinUploader(config).login()
        return

    if args.command == "upload":
        DouyinUploader(config).upload_from_records()
        return

    if args.command == "run":
        print_parse_summary(parse_invoices(config))
        DouyinUploader(config).upload_from_records()
        return


if __name__ == "__main__":
    main()
