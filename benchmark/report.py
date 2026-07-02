from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from metrics import RequestMetrics


@dataclass
class EndpointStats:
    endpoint: str
    ttft_mean: float
    ttft_median: float
    ttft_p95: float
    total_mean: float
    tps_mean: float
    quality_pass_rate: float
    quality_score_mean: float
    success_rate: float
    request_count: int


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def aggregate(metrics: list[RequestMetrics]) -> list[EndpointStats]:
    by_endpoint: dict[str, list[RequestMetrics]] = {}
    for m in metrics:
        by_endpoint.setdefault(m.endpoint, []).append(m)

    results = []
    for endpoint, items in by_endpoint.items():
        successful = [m for m in items if m.success]
        ttft_vals = [m.ttft_ms for m in successful if m.ttft_ms > 0]
        total_vals = [m.total_ms for m in successful]
        tps_vals = [m.tps for m in successful if m.tps > 0]
        quality_items = [m for m in items if m.success]
        passed = sum(1 for m in quality_items if m.quality_passed)
        scores = [m.quality_score for m in quality_items]

        results.append(EndpointStats(
            endpoint=endpoint,
            ttft_mean=round(statistics.mean(ttft_vals), 2) if ttft_vals else 0.0,
            ttft_median=round(statistics.median(ttft_vals), 2) if ttft_vals else 0.0,
            ttft_p95=round(_percentile(ttft_vals, 95), 2) if ttft_vals else 0.0,
            total_mean=round(statistics.mean(total_vals), 2) if total_vals else 0.0,
            tps_mean=round(statistics.mean(tps_vals), 2) if tps_vals else 0.0,
            quality_pass_rate=round(passed / len(quality_items) * 100, 1) if quality_items else 0.0,
            quality_score_mean=round(statistics.mean(scores), 4) if scores else 0.0,
            success_rate=round(len(successful) / len(items) * 100, 1) if items else 0.0,
            request_count=len(items),
        ))
    return results


def aggregate_by_case(metrics: list[RequestMetrics]) -> list[dict]:
    groups: dict[str, dict[str, list[RequestMetrics]]] = {}
    for m in metrics:
        groups.setdefault(m.test_id, {}).setdefault(m.endpoint, []).append(m)

    rows = []
    for test_id, ep_items in groups.items():
        first = next(iter(next(iter(ep_items.values()))))
        row = {"test_id": test_id, "category": first.category, "test_name": first.test_name}
        for endpoint, items in ep_items.items():
            successful = [m for m in items if m.success]
            ttft = [m.ttft_ms for m in successful if m.ttft_ms > 0]
            passed = sum(1 for m in successful if m.quality_passed)
            row[f"{endpoint}_ttft_ms"] = round(statistics.mean(ttft), 2) if ttft else 0.0
            row[f"{endpoint}_total_ms"] = round(statistics.mean([m.total_ms for m in successful]), 2) if successful else 0.0
            row[f"{endpoint}_tps"] = round(statistics.mean([m.tps for m in successful if m.tps > 0]), 2) if successful else 0.0
            row[f"{endpoint}_quality_pass"] = f"{passed}/{len(successful)}" if successful else "0/0"
            row[f"{endpoint}_quality_score"] = round(statistics.mean([m.quality_score for m in successful]), 4) if successful else 0.0
        rows.append(row)
    return rows


def print_summary(stats: list[EndpointStats]) -> None:
    print("\n" + "=" * 90)
    print("  延迟与质量对比汇总")
    print("=" * 90)
    header = f"{'端点':<22} {'TTFT均值':>10} {'TTFT中位':>10} {'TTFT P95':>10} {'总耗时':>10} {'TPS':>8} {'质量通过率':>10} {'质量均分':>10} {'成功率':>8}"
    print(header)
    print("-" * 90)
    for s in stats:
        print(
            f"{s.endpoint:<22} {s.ttft_mean:>10.1f} {s.ttft_median:>10.1f} {s.ttft_p95:>10.1f}"
            f" {s.total_mean:>10.1f} {s.tps_mean:>8.1f} {s.quality_pass_rate:>9.1f}% {s.quality_score_mean:>10.4f} {s.success_rate:>7.1f}%"
        )
    print("=" * 90)
    print("  TTFT = 首字延迟(ms)  TPS = 每秒输出token数  质量通过率 = 自动评估通过百分比\n")


def print_case_detail(rows: list[dict]) -> None:
    print("=" * 110)
    print("  按测试用例明细")
    print("=" * 110)
    if not rows:
        print("  无数据")
        return
    endpoints = [k.rsplit("_ttft_ms", 1)[0] for k in rows[0] if k.endswith("_ttft_ms")]
    for row in rows:
        print(f"\n  [{row['category']}] {row['test_id']}: {row['test_name']}")
        for ep in endpoints:
            ttft = row.get(f"{ep}_ttft_ms", 0)
            total = row.get(f"{ep}_total_ms", 0)
            tps = row.get(f"{ep}_tps", 0)
            qp = row.get(f"{ep}_quality_pass", "0/0")
            qs = row.get(f"{ep}_quality_score", 0)
            print(f"    {ep:<22} TTFT={ttft:>8.1f}ms  总耗时={total:>8.1f}ms  TPS={tps:>6.1f}  通过={qp:<6}  得分={qs:.4f}")


def save_reports(metrics: list[RequestMetrics], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = output_dir / "raw_results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for m in metrics:
            f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")

    csv_path = output_dir / "raw_results.csv"
    if metrics:
        fields = list(metrics[0].to_dict().keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for m in metrics:
                writer.writerow(m.to_dict())

    case_rows = aggregate_by_case(metrics)
    case_csv = output_dir / "case_summary.csv"
    if case_rows:
        fields = list(case_rows[0].keys())
        with case_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in case_rows:
                writer.writerow(row)

    print(f"\n  报告已保存至 {output_dir}/")
    print(f"    - raw_results.jsonl  (逐次请求原始数据)")
    print(f"    - raw_results.csv    (CSV 格式，便于 Excel 分析)")
    print(f"    - case_summary.csv   (按测试用例汇总)")
