"""壓力測試報告產生器"""

from dataclasses import dataclass, field
import json
import statistics


@dataclass
class RequestResult:
    client_id: int
    round_idx: int
    message: str
    status_code: int
    total_s: float
    ttfa_s: float | None = None
    error: str | None = None
    events: list[str] = field(default_factory=list)


def generate_report(results: list[RequestResult], concurrency: int, mode: str) -> str:
    """產生 Markdown 格式報告"""
    successful = [r for r in results if r.error is None and r.status_code == 200]
    failed = [r for r in results if r.error is not None or r.status_code != 200]

    totals = [r.total_s for r in successful]
    ttfas = [r.ttfa_s for r in successful if r.ttfa_s is not None]

    lines = [
        "# 壓力測試報告",
        "",
        "| 項目 | 值 |",
        "|------|-----|",
        f"| 並發數 | {concurrency} |",
        f"| 模式 | {mode} |",
        f"| 總請求數 | {len(results)} |",
        f"| 成功 | {len(successful)} |",
        f"| 失敗 | {len(failed)} |",
    ]

    if results:
        lines.append(f"| 成功率 | {len(successful) / len(results) * 100:.1f}% |")

    lines.append("")

    if totals:
        totals_sorted = sorted(totals)
        n = len(totals_sorted)
        p50 = totals_sorted[min(int(n * 0.5), n - 1)]
        p95 = totals_sorted[min(int(n * 0.95), n - 1)]
        p99 = totals_sorted[min(int(n * 0.99), n - 1)]

        avg_total = f"{statistics.mean(totals):.2f}"
        avg_ttfa = f"{statistics.mean(ttfas):.2f}" if ttfas else "-"

        lines.extend(
            [
                "## 延遲統計（秒）",
                "",
                "| 指標 | Total | TTFA |",
                "|------|-------|------|",
                f"| Avg | {avg_total} | {avg_ttfa} |",
                f"| P50 | {p50:.2f} | - |",
                f"| P95 | {p95:.2f} | - |",
                f"| P99 | {p99:.2f} | - |",
                f"| Min | {min(totals):.2f} | - |",
                f"| Max | {max(totals):.2f} | - |",
                "",
            ]
        )

    if failed:
        error_counts: dict[str, int] = {}
        for r in failed:
            key = r.error or f"HTTP {r.status_code}"
            error_counts[key] = error_counts.get(key, 0) + 1
        lines.extend(
            [
                "## 錯誤分佈",
                "",
                "| 錯誤 | 次數 |",
                "|------|------|",
            ]
        )
        for err, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {err} | {count} |")

    return "\n".join(lines)


def save_json(results: list[RequestResult], path: str) -> None:
    """儲存原始結果到 JSON"""
    data = [
        {
            "client_id": r.client_id,
            "round": r.round_idx,
            "message": r.message,
            "status": r.status_code,
            "total_s": r.total_s,
            "ttfa_s": r.ttfa_s,
            "error": r.error,
        }
        for r in results
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
