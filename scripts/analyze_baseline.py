"""Pipeline baseline 分析 — 讀 orders.db perf_metrics + logs/conversations/*.jsonl 產報告。

輸出 markdown：階段耗時分布、瓶頸分析、句子結構、常用回覆 top N、warmup cache 命中率、建議路徑。

Usage:
    uv run python scripts/analyze_baseline.py [--hours N] [--min-total N] [--top-k N] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 從 src 共用常數 / 快取，避免硬編碼漂移
from src.services.tts_cache import HIGH_FREQ_PHRASES, _normalize  # noqa: E402
from src.utils import SENTENCE_PUNCTS  # noqa: E402

DB_PATH = ROOT / "orders.db"
LOG_DIR = ROOT / "logs" / "conversations"

# 檔名前綴過濾（E2E 測試 / 開發殘留 / None session）
SKIP_PREFIXES = ("e2e-", "test-", "fix-", "None")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=float, default=None, help="只看 SQLite 最近 N 小時（預設全部）"
    )
    parser.add_argument(
        "--min-total", type=float, default=0.5, help="最小 total_s 門檻（過濾空回應 turn）"
    )
    parser.add_argument("--top-k", type=int, default=20, help="常用回覆 top K")
    parser.add_argument("--output", type=str, default=None, help="報告輸出路徑（預設 stdout）")
    return parser.parse_args()


def load_perf_rows(hours: float | None, min_total: float) -> tuple[list[dict], int]:
    """回傳 (過濾後 rows, 原始總筆數)。

    過濾規則：
    - total_s >= min_total（排除極短 session）
    - ttfa_s IS NOT NULL（排除 checkout state machine / shortcircuit 攔截的 noop turn，
      這些 turn 沒進 LLM 也沒送 TTS，dm_s 會是 0.001-0.01s 污染統計）
    """
    if not DB_PATH.exists():
        return [], 0
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        where_clauses = []
        params: list = []
        if hours is not None:
            cutoff = datetime.now().timestamp() - hours * 3600
            where_clauses.append("timestamp > ?")
            params.append(cutoff)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        total_count = conn.execute(
            f"SELECT COUNT(*) FROM perf_metrics {where_sql}",
            params,
        ).fetchone()[0]

        where_clauses.append("total_s >= ?")
        params.append(min_total)
        where_clauses.append("ttfa_s IS NOT NULL")
        where_sql = f"WHERE {' AND '.join(where_clauses)}"
        rows = conn.execute(
            f"SELECT timestamp, asr_s, dm_s, ttfa_s, tts_s, total_s FROM perf_metrics "
            f"{where_sql} ORDER BY timestamp DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows], total_count
    finally:
        conn.close()


def load_conversation_turns(min_total: float) -> tuple[list[dict], int, int]:
    """回傳 (turns, total_session_files_scanned, skipped_files_count)"""
    if not LOG_DIR.exists():
        return [], 0, 0

    turns: list[dict] = []
    total_files = 0
    skipped_files = 0

    for jsonl_path in sorted(LOG_DIR.glob("*.jsonl")):
        total_files += 1
        if jsonl_path.name.startswith(SKIP_PREFIXES):
            skipped_files += 1
            continue
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    perf = entry.get("perf") or {}
                    total_s = perf.get("total_s")
                    response = entry.get("response", "")
                    if total_s is None or total_s < min_total:
                        continue
                    if not response.strip():
                        continue
                    turns.append(
                        {
                            "ts": entry.get("ts"),
                            "asr_text": entry.get("asr_text", ""),
                            "response": _THINK_RE.sub("", response).strip(),
                            "perf": perf,
                            "tool_calls": entry.get("tool_calls") or [],
                            "source_file": jsonl_path.name,
                        }
                    )
        except OSError:
            continue

    return turns, total_files, skipped_files


def percentiles(values: list[float], ps=(50, 90, 99)) -> dict[int, float | None]:
    """手算百分位，容忍樣本數少。"""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return {p: None for p in ps}
    result: dict[int, float | None] = {}
    n = len(clean)
    for p in ps:
        if n == 1:
            result[p] = clean[0]
            continue
        idx = (p / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        frac = idx - lo
        result[p] = clean[lo] * (1 - frac) + clean[hi] * frac
    return result


def split_sentences(text: str) -> list[str]:
    """用 SENTENCE_PUNCTS 切句（簡化版，不套 MIN/MAX 閾值，for baseline 統計夠用）"""
    result: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in SENTENCE_PUNCTS:
            s = buf.strip()
            if s:
                result.append(s)
            buf = ""
    if buf.strip():
        result.append(buf.strip())
    return result


def build_warmup_lookup() -> set[str]:
    """正規化後的 warmup 句子集合（tts_cache 用正規化 key 做 lookup）"""
    lookup: set[str] = set()
    for phrase in HIGH_FREQ_PHRASES:
        lookup.add(phrase)
        lookup.add(_normalize(phrase))
    return lookup


def is_warmup_hit(sentence: str, lookup: set[str]) -> bool:
    return sentence in lookup or _normalize(sentence) in lookup


def fmt_secs(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else "-"


def fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def render_report(
    perf_rows: list[dict],
    perf_total_count: int,
    turns: list[dict],
    total_files: int,
    skipped_files: int,
    top_k: int,
    hours: float | None,
    min_total: float,
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = [f"# Pipeline Baseline Report — {today}", ""]

    # 資料範圍
    lines.append("## 資料範圍")
    hours_desc = f"最近 {hours}h" if hours is not None else "全部歷史"
    lines.append(
        f"- SQLite `perf_metrics`: {len(perf_rows)}/{perf_total_count} 筆"
        f"（{hours_desc}，過濾 total_s < {min_total} 的 noop）"
    )
    lines.append(
        f"- Conversation logs: {total_files} 個 jsonl "
        f"（跳過 {skipped_files} 個測試檔），{len(turns)} 個有效 turn（total_s >= {min_total} 且 response 非空）"
    )
    lines.append("")

    if not perf_rows and not turns:
        lines.append("> **沒有資料**。請跑 pipeline 累積 turn 後再試。")
        return "\n".join(lines)

    # 階段耗時分布（來自 SQLite，樣本較多）
    lines.append("## 階段耗時分布（秒，資料源 = SQLite perf_metrics）")
    stages = ("asr_s", "dm_s", "tts_s", "ttfa_s", "total_s")
    stage_pcts: dict[str, dict[int, float | None]] = {}
    stage_counts: dict[str, int] = {}
    for stage in stages:
        vals = [r[stage] for r in perf_rows if r.get(stage) is not None]
        stage_counts[stage] = len(vals)
        stage_pcts[stage] = percentiles(vals)
    lines.append("")
    lines.append("| 階段 | p50 | p90 | p99 | 樣本 |")
    lines.append("|------|-----|-----|-----|------|")
    for stage in stages:
        pcts = stage_pcts[stage]
        lines.append(
            f"| {stage} | {fmt_secs(pcts[50])} | {fmt_secs(pcts[90])} | "
            f"{fmt_secs(pcts[99])} | {stage_counts[stage]} |"
        )
    lines.append("")

    # 瓶頸分析（注意：dm_s / tts_s 並行重疊，總和可能 > total_s）
    lines.append("## 瓶頸分析")
    lines.append("")
    lines.append(
        "> **注意**：`dm_s` 和 `tts_s` 是 wall-clock 量測，"
        "在 streaming 模式下兩者重疊（TTS 第一句開始時 LLM 還在產生後續 token），"
        "所以不能用 sum 或比例對 total_s 來算瓶頸。看 **絕對秒數最大的** 才是瓶頸。"
    )
    lines.append("")
    biggest_stage: str | None = None
    biggest_p50 = 0.0
    for stage in ("asr_s", "dm_s", "tts_s"):
        v = stage_pcts[stage][50]
        if v is not None and v > biggest_p50:
            biggest_p50 = v
            biggest_stage = stage
    if biggest_stage:
        lines.append(
            f"- **p50 最大項**：`{biggest_stage}` = {biggest_p50:.3f}s"
            f"（p90 = {fmt_secs(stage_pcts[biggest_stage][90])}s）"
        )
    lines.append("")

    # 回覆結構（來自 conversation logs）
    if turns:
        sentence_counts = [len(split_sentences(t["response"])) for t in turns]
        response_lens = [len(t["response"]) for t in turns]
        sc_pcts = percentiles([float(x) for x in sentence_counts])
        rl_pcts = percentiles([float(x) for x in response_lens])

        lines.append("## 回覆結構（資料源 = conversation logs）")
        lines.append("")
        lines.append("| 指標 | p50 | p90 | max | 樣本 |")
        lines.append("|------|-----|-----|-----|------|")
        lines.append(
            f"| 句子數/turn | {fmt_secs(sc_pcts[50])} | {fmt_secs(sc_pcts[90])} | "
            f"{max(sentence_counts) if sentence_counts else 0} | {len(sentence_counts)} |"
        )
        lines.append(
            f"| 字元數/turn | {fmt_secs(rl_pcts[50])} | {fmt_secs(rl_pcts[90])} | "
            f"{max(response_lens) if response_lens else 0} | {len(response_lens)} |"
        )
        lines.append("")

    # 常用回覆 top K + warmup cache 命中
    lines.append(f"## 常用句子 Top {top_k}（全部 turn 的句子計數）")
    lines.append("")
    warmup_lookup = build_warmup_lookup()
    sentence_counter: Counter[str] = Counter()
    total_sentences = 0
    hit_sentences = 0
    for t in turns:
        for s in split_sentences(t["response"]):
            sentence_counter[s] += 1
            total_sentences += 1
            if is_warmup_hit(s, warmup_lookup):
                hit_sentences += 1

    if total_sentences > 0:
        hit_rate = hit_sentences / total_sentences
        lines.append(
            f"- **Warmup cache 命中率**：{hit_sentences}/{total_sentences} = **{fmt_pct(hit_rate)}**"
        )
        lines.append("")

    lines.append("### 全部 top N（含已命中的）")
    lines.append("")
    lines.append("| # | 次數 | 命中 | 字元 | 句子 |")
    lines.append("|---|------|------|------|------|")
    for i, (sentence, count) in enumerate(sentence_counter.most_common(top_k), 1):
        hit_mark = "Y" if is_warmup_hit(sentence, warmup_lookup) else " "
        preview = sentence if len(sentence) <= 50 else sentence[:47] + "..."
        lines.append(f"| {i} | {count} | {hit_mark} | {len(sentence)} | {preview} |")
    lines.append("")

    # P1 候選：top miss（未命中 warmup 的常用句）
    miss_counter: Counter[str] = Counter(
        {s: c for s, c in sentence_counter.items() if not is_warmup_hit(s, warmup_lookup)}
    )
    lines.append(f"### P1 候選：未命中 warmup 的 Top {top_k}（次數 >= 2）")
    lines.append("")
    lines.append("| # | 次數 | 字元 | 句子 |")
    lines.append("|---|------|------|------|")
    miss_top = [(s, c) for s, c in miss_counter.most_common(top_k) if c >= 2]
    if not miss_top:
        lines.append("| - | - | - | _沒有次數 >= 2 的未命中句子_ |")
    else:
        for i, (sentence, count) in enumerate(miss_top, 1):
            preview = sentence if len(sentence) <= 50 else sentence[:47] + "..."
            lines.append(f"| {i} | {count} | {len(sentence)} | {preview} |")
    lines.append("")

    # 建議
    lines.append("## 建議")
    lines.append("")
    recs: list[str] = []
    dm_p50 = stage_pcts["dm_s"][50]
    dm_p90 = stage_pcts["dm_s"][90]
    tts_p50 = stage_pcts["tts_s"][50]

    # P2 條件：LLM 是最大瓶頸（比 TTS 大 50% 以上 或 p90 超 5s）
    if biggest_stage == "dm_s" and dm_p50:
        if (tts_p50 and dm_p50 > tts_p50 * 1.5) or (dm_p90 and dm_p90 > 5.0):
            ratio_desc = f"，是 tts_s 的 {dm_p50 / tts_p50:.1f}x" if tts_p50 and tts_p50 > 0 else ""
            recs.append(
                f"**P2 (Speculative Decoding) 最優先** — dm_s p50 {dm_p50:.2f}s / "
                f"p90 {fmt_secs(dm_p90)}s{ratio_desc}。LLM 30-50% 加速直接縮短 TTFA。"
                f"先確認 Qwen3.5-9B tokenizer 相容的 0.5B draft 模型"
            )

    # P0 條件：TTS 是瓶頸 且 句子數多（至少 3 句才有並行收益）
    if turns and tts_p50 and tts_p50 > 1.5:
        sc_p50 = percentiles([float(len(split_sentences(t["response"]))) for t in turns])[50]
        if sc_p50 and sc_p50 >= 3:
            recs.append(
                f"**P0 (asyncio.Queue 解耦)** — tts_s p50 {tts_p50:.2f}s + 句子數 "
                f"p50 {sc_p50:.1f}，有並行收益空間"
            )

    # P1 條件：warmup miss top 有 >=3 次重複
    if miss_top and miss_top[0][1] >= 3:
        recs.append(
            f"**P1 (TTS prewarming 擴充)** — 未命中 top 次數 {miss_top[0][1]}，"
            f"共 {len(miss_top)} 條高頻 miss 候選（注意過濾 ASR 殘留短片段）"
        )

    if not recs:
        recs.append("資料不足以下明確建議，建議補 10-15 輪真實對話再跑一次")
    for r in recs:
        lines.append(f"- {r}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    perf_rows, perf_total_count = load_perf_rows(args.hours, args.min_total)
    turns, total_files, skipped_files = load_conversation_turns(args.min_total)
    report = render_report(
        perf_rows=perf_rows,
        perf_total_count=perf_total_count,
        turns=turns,
        total_files=total_files,
        skipped_files=skipped_files,
        top_k=args.top_k,
        hours=args.hours,
        min_total=args.min_total,
    )
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        # Windows cp950 console 無法印 Unicode（報告含中文），強制 utf-8
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
