from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import TestConfig, default_endpoints
from report import aggregate, aggregate_by_case, print_case_detail, print_summary, save_reports
from runner import run_benchmark
from test_cases import all_test_cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DeepSeek V4 Flash 对比基准测试：opencode Go 端点 vs DeepSeek 官方 API",
    )
    parser.add_argument(
        "command",
        choices=["run", "list"],
        help="run=执行基准测试；list=列出所有测试用例",
    )
    parser.add_argument("--runs", type=int, default=5, help="每个测试用例的重复次数（默认 5）")
    parser.add_argument("--max-tokens", type=int, default=1024, help="单次最大输出 token 数（默认 1024）")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度（默认 0.0，保证可复现）")
    parser.add_argument("--timeout", type=float, default=60.0, help="单次请求超时秒数（默认 60）")
    parser.add_argument("--cases", type=str, default="", help="只运行指定用例，逗号分隔（如 code_prime,reasoning_transitive）")
    parser.add_argument("--output", type=str, default="results", help="结果输出目录（默认 results）")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "list":
        cases = all_test_cases()
        print(f"共 {len(cases)} 个测试用例：\n")
        for tc in cases:
            print(f"  [{tc.category:<14}] {tc.id:<22} {tc.name}")
        return

    endpoints = default_endpoints()
    active = [e for e in endpoints if e.enabled]
    if not active:
        print("错误：未检测到 API Key。请设置环境变量：", file=sys.stderr)
        print("  export OPENCODE_GO_API_KEY=\"你的Go套餐key\"", file=sys.stderr)
        print("  export DEEPSEEK_API_KEY=\"你的官方API key\"", file=sys.stderr)
        sys.exit(1)

    disabled = [e.name for e in endpoints if not e.enabled]
    if disabled:
        print(f"提示：以下端点缺少 API Key，已跳过: {', '.join(disabled)}\n")

    print("激活端点：")
    for e in active:
        print(f"  - {e.name}: {e.base_url} (model: {e.model})")
    print()

    test_config = TestConfig(
        runs_per_case=args.runs,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )

    cases = all_test_cases()
    if args.cases:
        selected = {c.strip() for c in args.cases.split(",") if c.strip()}
        cases = [tc for tc in cases if tc.id in selected]
        if not cases:
            print(f"错误：未找到匹配的测试用例: {args.cases}", file=sys.stderr)
            sys.exit(1)

    print(f"测试用例: {len(cases)} 个 x {test_config.runs_per_case} 次 x {len(active)} 端点 = {len(cases) * test_config.runs_per_case * len(active)} 次请求\n")
    print("开始测试...\n")

    metrics = list(run_benchmark(active, cases, test_config))

    print("\n测试完成，生成报告...\n")
    stats = aggregate(metrics)
    print_summary(stats)
    print_case_detail(aggregate_by_case(metrics))

    output_dir = Path(__file__).parent / args.output
    save_reports(metrics, output_dir)


if __name__ == "__main__":
    main()
