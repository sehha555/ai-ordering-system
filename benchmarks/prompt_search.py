"""
Autoresearch 風格 Prompt Search — 自動迭代 system prompt / tool description 變體

用法：
  python -m benchmarks.prompt_search                          # 完整搜索
  python -m benchmarks.prompt_search --quick-only            # 只跑快速篩選（debug）
  python -m benchmarks.prompt_search --dimensions tool_desc  # 只搜索特定維度
  python -m benchmarks.prompt_search --dimensions tool_desc,system_rules
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# 確保 project root 在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ============ Hard Cases 子集（穩定失敗 7 個）============

# 根據 MEMORY.md 記錄的穩定失敗案例 + 過去 run 觀察到的不穩定案例
HARD_CASE_IDS: list[str] = [
    "u_query_menu_drinks",  # A8: query_menu — 模型傾向靠記憶直接回覆
    "u_riceball_all_info",  # B1: 飯糰一次給齊 — 間歇失敗
    "u_intent_big_iced_milk",  # D4: 大冰奶俗稱識別 — 訓練知識干擾
    "u_combo_missing_temp",  # G1: 套餐缺飲料溫度 — 9B 極限
    "u_modify_empty_cart",  # I3: 修改但購物車空 — keyword 觸發
    "u_multi_item_complex",  # J2: 大量品項混合 — 9B 極限
    "u_combo_alias",  # G2: 套餐別名 — 間歇失敗
]

# ============ 搜索維度定義 ============

# add_item description 變體
ADD_ITEM_DESC_VARIANTS: list[str] = [
    # V0: baseline（目前 production 文字）
    (
        "加入品項到購物車。所有點餐請求必須透過此工具，禁止跳過直接回覆。"
        "name 填菜單品項名稱"
        "（如「香燻培根飯糰」「原味蛋餅」「培根蛋吐司」「純鮮奶茶」「套餐一」「薯餅(1片)」）。"
        "不確定品項名稱也要呼叫，後端會自動比對。"
        "飯糰額外必填 rice；飲料額外必填 size 和 temp；套餐額外必填 temp。"
        "缺少必填欄位時回傳 ok:false 和追問訊息。"
    ),
    # V1: 強調「不確定也要 call」+ 俗稱示例
    (
        "加入品項到購物車。所有點餐請求必須透過此工具，禁止跳過直接回覆。"
        "name 填菜單品項名稱或俗稱"
        "（如「香燻培根飯糰」「原味蛋餅」「培根蛋吐司」「純鮮奶茶」「套餐一」「薯餅(1片)」"
        '「大冰奶」→name="純鮮奶茶"）。'
        "不確定品項名稱也要呼叫，後端會自動比對；絕不能靠記憶直接回覆點餐結果。"
        "飯糰額外必填 rice；飲料額外必填 size 和 temp；套餐額外必填 temp。"
        "缺少必填欄位時回傳 ok:false 和追問訊息。"
    ),
    # V2: 更強的負面約束 + 明確禁令
    (
        "加入品項到購物車。所有點餐請求必須透過此工具，絕對不能跳過直接回覆點餐結果。"
        "name 填菜單品項名稱"
        "（如「香燻培根飯糰」「原味蛋餅」「培根蛋吐司」「純鮮奶茶」「套餐一」「薯餅(1片)」）。"
        "不確定品項名稱也要呼叫，後端會自動比對。"
        "飯糰額外必填 rice；飲料額外必填 size 和 temp；套餐額外必填 temp。"
        "缺少必填欄位時回傳 ok:false 並由系統決定追問訊息，不能自行猜測補值。"
    ),
]

# query_menu description 變體
QUERY_MENU_DESC_VARIANTS: list[str] = [
    # V0: baseline
    (
        "當客人問有什麼可以點、詢問菜單內容時必須調用，禁止靠記憶直接回覆菜單。"
        "回傳分類清單或指定分類的品項（含售罄狀態與價格）；飯糰分類額外附成分表。"
        "category 不填則回傳所有分類名稱。"
    ),
    # V1: 加強「查飲料必須 call」+ 負面約束
    (
        "當客人問有什麼可以點、詢問菜單內容時必須調用，禁止靠記憶直接回覆菜單。"
        '包含查詢特定分類（如「有什麼飲料」→ category="飲品"）。'
        "回傳分類清單或指定分類的品項（含售罄狀態與價格）；飯糰分類額外附成分表。"
        "category 不填則回傳所有分類名稱。"
        "禁止不呼叫就直接列出菜單內容。"
    ),
    # V2: 簡潔版（減少冗餘描述）
    (
        "查詢菜單。客人問有什麼可點或詢問分類品項時必須調用，不得靠訓練記憶直接回覆。"
        "category 填分類名稱（飯糰/飲品/蛋餅/吐司/漢堡/饅頭/點心/果醬吐司/套餐），"
        "不填則回傳全分類列表。"
    ),
]

# system prompt Core Rules 變體（修改 system_prompt.md 中的核心規則措辭）
# 注意：這裡用 overlay 函數注入，不改源檔
SYSTEM_RULES_VARIANTS: list[str] = [
    # V0: baseline（不注入額外規則，使用原始 system_prompt）
    "",
    # V1: 在 system prompt 末尾追加強化規則
    (
        "\n\n## 額外強制規則\n"
        "- 客人提到任何飲料俗稱（大冰奶/小冰奶/波霸等）必須對應到菜單品項後呼叫 add_item\n"
        "- 購物車為空時，不可描述「沒有可修改的」以外的操作\n"
        "- 查詢菜單時，任何情況下都必須先呼叫 query_menu 才能列出品項"
    ),
    # V2: 更精煉的強化規則（針對套餐別名）
    (
        "\n\n## 核心行為準則（補充）\n"
        "- 俗稱映射：大冰奶→純鮮奶茶(大杯/冰)；四號餐/四餐→套餐四；中溫=中杯溫\n"
        "- 購物車狀態：空購物車時說「沒有」，不呼叫工具\n"
        "- 菜單查詢：必須透過 query_menu 工具，不靠記憶"
    ),
]

# ============ 維度組合定義 ============

DIMENSION_MAP: dict[str, list[Any]] = {
    "add_item_desc": ADD_ITEM_DESC_VARIANTS,
    "query_menu_desc": QUERY_MENU_DESC_VARIANTS,
    "system_rules": SYSTEM_RULES_VARIANTS,
}


def _build_variant_combinations(dimensions: list[str]) -> list[dict[str, int]]:
    """
    依指定維度建立所有變體組合（笛卡兒積）。

    回傳每個組合的 {dimension_name: variant_index} dict。
    """
    import itertools

    dim_indices = [range(len(DIMENSION_MAP[d])) for d in dimensions]
    combos = []
    for indices in itertools.product(*dim_indices):
        combo: dict[str, int] = {}
        for dim, idx in zip(dimensions, indices):
            combo[dim] = idx
        combos.append(combo)
    return combos


def _is_baseline(combo: dict[str, int]) -> bool:
    """判斷是否為 baseline（所有維度都是 index 0）"""
    return all(v == 0 for v in combo.values())


# ============ Prompt Override 機制 ============


def _apply_tool_desc_override(
    tools_schema: list[dict],
    add_item_desc: str | None,
    query_menu_desc: str | None,
) -> list[dict]:
    """深度複製 tools_schema 並套用 description override。"""
    schema = copy.deepcopy(tools_schema)
    for tool in schema:
        fn = tool.get("function", {})
        name = fn.get("name", "")
        if name == "add_item" and add_item_desc is not None:
            fn["description"] = add_item_desc
        elif name == "query_menu" and query_menu_desc is not None:
            fn["description"] = query_menu_desc
    return schema


def _apply_system_rules_override(system_prompt: str, rules_suffix: str) -> str:
    """將 rules_suffix 追加到 system_prompt 末尾（空字串表示不修改）。"""
    if not rules_suffix:
        return system_prompt
    return system_prompt + rules_suffix


# ============ 單一 Adapter Run（含 Override）============


def _run_case_with_override(
    adapter,
    case: dict,
    timeout: int,
    override_system_prompt: str | None = None,
    override_tools_schema: list[dict] | None = None,
) -> dict:
    """
    執行單一 test case，支援 runtime override。

    透過直接覆寫 adapter instance attribute 實現 monkey-patch，
    不修改原始源檔案。
    """
    # 暫存原始值
    orig_system_prompt = adapter._system_prompt
    orig_tools_schema = adapter._tools_schema

    try:
        # 套用 override
        if override_system_prompt is not None:
            adapter._system_prompt = override_system_prompt
        if override_tools_schema is not None:
            adapter._tools_schema = override_tools_schema

        return adapter.run(case, timeout=timeout)
    finally:
        # 確保恢復（即使 exception 也執行）
        adapter._system_prompt = orig_system_prompt
        adapter._tools_schema = orig_tools_schema


# ============ 評分函數 ============


def _score_single_run(run_result: dict, case_data: dict) -> dict:
    """
    對單次 run 結果評分，回傳 {passed, f1, response_score, fail_reason}。
    """
    from benchmarks.metrics.llm_metrics import tool_call_match, response_score

    if not run_result.get("success", True):
        error_msg = run_result.get("error", "unknown")
        return {
            "passed": False,
            "f1": 0.0,
            "response_score": 0.0,
            "fail_reason": f"error:{error_msg}",
        }

    expected_tools = case_data.get("expected_tools", [])
    expected_contains = case_data.get("expected_response_contains", [])
    expected_args = case_data.get("expected_args", None)

    tool_calls = run_result.get("tool_calls", [])
    response = run_result.get("response", "")

    scores = tool_call_match(tool_calls, expected_tools, expected_args)
    rs = response_score(response, expected_contains, tool_calls, expected_tools)

    pass_threshold = 0.8
    passed = scores["f1"] >= pass_threshold and rs["score"] >= pass_threshold

    fail_reason = None
    if not passed:
        if scores["f1"] < pass_threshold:
            fail_reason = f"tool_f1={scores['f1']:.2f}"
        else:
            fail_reason = f"resp_score={rs['score']:.2f}({','.join(rs['penalties'])})"

    return {
        "passed": passed,
        "f1": scores["f1"],
        "response_score": rs["score"],
        "fail_reason": fail_reason,
    }


def _run_subset(
    adapter,
    test_data: list[dict],
    case_ids: list[str],
    timeout: int,
    repeat: int = 1,
    override_system_prompt: str | None = None,
    override_tools_schema: list[dict] | None = None,
    label: str = "",
) -> dict:
    """
    跑指定 case_ids 子集，回傳 {pass_rate, case_results}。

    case_results: [{case_id, passed, avg_f1, fail_reason}, ...]
    """
    # 建立子集（依 case_ids 過濾）
    target_ids = set(case_ids)
    subset = [d for d in test_data if d["id"] in target_ids]

    case_results = []
    passed_count = 0

    for case_data in subset:
        case_id = case_data["id"]
        runs_score = []

        for r in range(repeat):
            start = time.perf_counter()
            try:
                run_result = _run_case_with_override(
                    adapter,
                    case_data,
                    timeout=timeout,
                    override_system_prompt=override_system_prompt,
                    override_tools_schema=override_tools_schema,
                )
                run_result["success"] = True
                run_result["latency"] = time.perf_counter() - start
            except Exception as e:
                run_result = {
                    "success": False,
                    "error": str(e),
                    "latency": time.perf_counter() - start,
                    "tool_calls": [],
                    "response": "",
                }

            score = _score_single_run(run_result, case_data)
            runs_score.append(score)

        # 只要任一 repeat 通過就算案例通過
        case_passed = any(s["passed"] for s in runs_score)
        avg_f1 = sum(s["f1"] for s in runs_score) / len(runs_score)
        fail_reasons = [s["fail_reason"] for s in runs_score if s["fail_reason"]]

        if case_passed:
            passed_count += 1

        case_results.append(
            {
                "case_id": case_id,
                "passed": case_passed,
                "avg_f1": avg_f1,
                "fail_reason": fail_reasons[0] if fail_reasons else None,
            }
        )

    total = len(subset)
    pass_rate = passed_count / total if total > 0 else 0.0

    prefix = f"[{label}] " if label else ""
    print(
        f"  {prefix}通過 {passed_count}/{total} ({pass_rate:.0%}) | "
        + " ".join(
            ("OK" if r["passed"] else "FAIL") + f":{r['case_id'].split('_', 1)[-1]}"
            for r in case_results
        )
    )

    return {"pass_rate": pass_rate, "case_results": case_results}


def _run_full(
    adapter,
    test_data: list[dict],
    timeout: int,
    repeat: int = 3,
    override_system_prompt: str | None = None,
    override_tools_schema: list[dict] | None = None,
    label: str = "",
) -> dict:
    """
    跑全部測試案例（repeat 次），回傳 {pass_rate, case_verdicts}。
    """
    from benchmarks.metrics.llm_metrics import compute_llm_metrics

    case_results_raw: list[dict] = []

    total = len(test_data)
    for idx, case_data in enumerate(test_data, 1):
        case_id = case_data["id"]
        runs: list[dict] = []

        for _ in range(repeat):
            start = time.perf_counter()
            try:
                run_result = _run_case_with_override(
                    adapter,
                    case_data,
                    timeout=timeout,
                    override_system_prompt=override_system_prompt,
                    override_tools_schema=override_tools_schema,
                )
                run_result["success"] = True
                run_result["latency"] = time.perf_counter() - start
            except Exception as e:
                run_result = {
                    "success": False,
                    "error": str(e),
                    "latency": time.perf_counter() - start,
                    "tool_calls": [],
                    "response": "",
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                }
            runs.append(run_result)

        case_results_raw.append({"case_id": case_id, "runs": runs})

        # 即時顯示進度（每 5 個顯示一次）
        if idx % 5 == 0 or idx == total:
            print(f"    [{label}] 進度 {idx}/{total}...", flush=True)

    summary = compute_llm_metrics(case_results_raw, test_data)
    pass_rate = summary.get("scenario_pass_rate", 0.0)
    verdicts = summary.get("case_verdicts", [])

    failed = [v for v in verdicts if not v["passed"]]
    print(
        f"  [{label}] 完整驗證: {pass_rate:.1%} | "
        f"失敗 {len(failed)} 個: {[v['case_id'] for v in failed]}"
    )

    return {"pass_rate": pass_rate, "case_verdicts": verdicts}


# ============ 主搜索邏輯 ============


def _build_overrides(
    combo: dict[str, int],
    base_system_prompt: str,
    base_tools_schema: list[dict],
) -> tuple[str, list[dict]]:
    """
    根據 combo 的 variant index，建立 override system_prompt 和 tools_schema。
    """
    # tool description overrides
    add_item_desc = None
    query_menu_desc = None

    if "add_item_desc" in combo:
        add_item_desc = ADD_ITEM_DESC_VARIANTS[combo["add_item_desc"]]
    if "query_menu_desc" in combo:
        query_menu_desc = QUERY_MENU_DESC_VARIANTS[combo["query_menu_desc"]]

    # system rules override
    rules_suffix = ""
    if "system_rules" in combo:
        rules_suffix = SYSTEM_RULES_VARIANTS[combo["system_rules"]]

    new_system_prompt = _apply_system_rules_override(base_system_prompt, rules_suffix)
    new_tools_schema = _apply_tool_desc_override(base_tools_schema, add_item_desc, query_menu_desc)

    return new_system_prompt, new_tools_schema


def _combo_label(combo: dict[str, int]) -> str:
    """將 combo dict 轉成可讀標籤，如 add_item_desc=V1,system_rules=V0"""
    return ",".join(f"{k}=V{v}" for k, v in sorted(combo.items()))


def _diff_descriptions(
    base_schema: list[dict],
    variant_schema: list[dict],
    base_rules: str,
    variant_system: str,
) -> dict:
    """比較 baseline 與 variant 的差異，產生 diff dict。"""
    diff: dict[str, Any] = {}

    # tool description diff
    base_map = {t["function"]["name"]: t["function"]["description"] for t in base_schema}
    var_map = {t["function"]["name"]: t["function"]["description"] for t in variant_schema}
    for name in ("add_item", "query_menu"):
        if base_map.get(name) != var_map.get(name):
            diff[f"{name}_desc"] = {
                "before": base_map.get(name, ""),
                "after": var_map.get(name, ""),
            }

    # system rules diff（只記錄追加部分）
    if variant_system != base_rules:
        appended = variant_system[len(base_rules) :]
        diff["system_rules_appended"] = appended.strip()

    return diff


def run_prompt_search(
    dimensions: list[str],
    quick_only: bool = False,
    hard_case_ids: list[str] | None = None,
) -> dict:
    """
    主搜索流程。

    Returns:
        搜索報告 dict（也會寫入 reports/prompt_search_{timestamp}.json）
    """
    if hard_case_ids is None:
        hard_case_ids = HARD_CASE_IDS

    # 載入 benchmark config
    import yaml

    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    repeat_full = config["benchmark"]["repeat"]  # 3
    timeout = config["benchmark"]["timeout"]

    # 載入測試資料
    data_path = Path(__file__).parent / "test_data" / "llm" / "test_scenarios.json"
    with open(data_path, encoding="utf-8") as f:
        test_data: list[dict] = json.load(f)

    print("\n=== Prompt Search 啟動 ===")
    print(f"搜索維度: {dimensions}")
    print(f"Hard cases: {hard_case_ids}")
    print(f"測試資料: {len(test_data)} 個場景")

    # 建立 adapter（使用 config 中的第一個 LLM 模型）
    from benchmarks.adapters.llm_adapters import create_llm_adapter

    llm_config = config["llm"]["models"][0]
    adapter = create_llm_adapter(llm_config["adapter"], llm_config.get("params", {}))

    # 預先載入 static context（baseline）
    adapter._ensure_static_context()
    base_system_prompt: str = adapter._system_prompt  # type: ignore[assignment]
    base_tools_schema: list[dict] = adapter._tools_schema  # type: ignore[assignment]

    print("\n[暖機] 執行暖機 run...")
    try:
        adapter.run(test_data[0], timeout=timeout)
        print("  暖機完成")
    except Exception as e:
        print(f"  暖機失敗（忽略）: {e}")

    # 計算 baseline 分數（快速篩選）
    print("\n[Baseline] 跑 hard cases 子集...")
    baseline_quick = _run_subset(
        adapter,
        test_data,
        hard_case_ids,
        timeout,
        repeat=1,
        label="baseline-quick",
    )
    baseline_quick_rate = baseline_quick["pass_rate"]

    candidates: list[dict] = []
    all_variant_results: list[dict] = []

    # 建立所有變體組合（排除 baseline）
    combos = _build_variant_combinations(dimensions)
    non_baseline_combos = [c for c in combos if not _is_baseline(c)]
    total_combos = len(non_baseline_combos)

    print(f"\n=== 開始搜索 {total_combos} 個非 baseline 變體 ===\n")

    for combo_idx, combo in enumerate(non_baseline_combos, 1):
        label = _combo_label(combo)
        print(f"[{combo_idx}/{total_combos}] 測試變體: {label}")

        new_system_prompt, new_tools_schema = _build_overrides(
            combo, base_system_prompt, base_tools_schema
        )

        # 階段一：快速篩選（只跑 hard cases，1 次）
        quick_result = _run_subset(
            adapter,
            test_data,
            hard_case_ids,
            timeout,
            repeat=1,
            override_system_prompt=new_system_prompt,
            override_tools_schema=new_tools_schema,
            label="quick",
        )
        quick_rate = quick_result["pass_rate"]

        variant_entry: dict[str, Any] = {
            "combo": combo,
            "label": label,
            "quick_pass_rate": quick_rate,
            "quick_baseline": baseline_quick_rate,
            "quick_improvement": quick_rate - baseline_quick_rate,
            "entered_full_validation": False,
            "full_pass_rate": None,
            "full_baseline": None,
            "is_candidate": False,
            "diff": _diff_descriptions(
                base_tools_schema,
                new_tools_schema,
                base_system_prompt,
                new_system_prompt,
            ),
            "hard_case_results": quick_result["case_results"],
        }

        # 如果快速篩選沒有改善，或 quick_only，跳過完整驗證
        improved = quick_rate > baseline_quick_rate
        if not improved:
            print(
                f"  快速篩選未改善（{quick_rate:.0%} <= {baseline_quick_rate:.0%}），跳過完整驗證\n"
            )
            all_variant_results.append(variant_entry)
            continue

        print(
            f"  快速篩選改善！{baseline_quick_rate:.0%} → {quick_rate:.0%}"
            f"（+{quick_rate - baseline_quick_rate:.0%}）"
        )

        if quick_only:
            print("  （--quick-only 模式，跳過完整驗證）\n")
            variant_entry["entered_full_validation"] = False
            all_variant_results.append(variant_entry)
            continue

        # 階段二：完整驗證（跑全部 53 cases x repeat 次）
        print(f"  進入完整驗證（{len(test_data)} 案例 x {repeat_full} 次）...")

        # 先取得 baseline 完整分數（只在第一個需要完整驗證的變體前跑一次）
        if not any(v.get("full_baseline") is not None for v in all_variant_results):
            print("  計算 baseline 完整分數...")
            baseline_full = _run_full(
                adapter, test_data, timeout, repeat=repeat_full, label="baseline-full"
            )
            baseline_full_rate = baseline_full["pass_rate"]
            # 回填所有已跑的 variant_entry
            for v in all_variant_results:
                v["full_baseline"] = baseline_full_rate
        else:
            # 從已有的記錄取得
            baseline_full_rate = next(
                v["full_baseline"]
                for v in all_variant_results
                if v.get("full_baseline") is not None
            )

        full_result = _run_full(
            adapter,
            test_data,
            timeout,
            repeat=repeat_full,
            override_system_prompt=new_system_prompt,
            override_tools_schema=new_tools_schema,
            label=f"full-{label}",
        )
        full_rate = full_result["pass_rate"]

        variant_entry["entered_full_validation"] = True
        variant_entry["full_pass_rate"] = full_rate
        variant_entry["full_baseline"] = baseline_full_rate
        variant_entry["full_improvement"] = full_rate - baseline_full_rate
        variant_entry["full_case_verdicts"] = full_result["case_verdicts"]

        is_candidate = full_rate >= baseline_full_rate
        variant_entry["is_candidate"] = is_candidate

        if is_candidate:
            candidates.append(variant_entry)
            print(
                f"  完整驗證通過！{baseline_full_rate:.1%} → {full_rate:.1%}"
                f"（+{full_rate - baseline_full_rate:.1%}）"
            )
            print(f"  >> 記錄為候選變體: {label}\n")
        else:
            print(
                f"  完整驗證退化 {baseline_full_rate:.1%} → {full_rate:.1%}"
                f"（{full_rate - baseline_full_rate:.1%}），淘汰\n"
            )

        all_variant_results.append(variant_entry)

    # ============ 整理結果 ============

    # 找最佳候選
    best_candidate = None
    if candidates:
        best_candidate = max(candidates, key=lambda c: c.get("full_pass_rate") or 0.0)

    # 輸出最終摘要
    print("\n=== 搜索完成 ===")
    print(f"測試變體數: {total_combos}")
    print(f"候選變體數: {len(candidates)}")
    if best_candidate:
        print(f"最佳候選: {best_candidate['label']}")
        print(f"  完整驗證: {best_candidate['full_pass_rate']:.1%}")
        if best_candidate.get("diff"):
            print(f"  Diff: {json.dumps(best_candidate['diff'], ensure_ascii=False, indent=2)}")
    else:
        print("無候選變體（所有變體均未達到 baseline 水準）")

    report = {
        "timestamp": datetime.now().isoformat(),
        "dimensions": dimensions,
        "hard_case_ids": hard_case_ids,
        "test_data_count": len(test_data),
        "baseline_quick_rate": baseline_quick_rate,
        "total_variants_tested": total_combos,
        "candidate_count": len(candidates),
        "best_candidate": best_candidate,
        "all_variants": all_variant_results,
    }

    # 儲存報告
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"prompt_search_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n報告已儲存: {report_path}")

    # 釋放 adapter 資源
    if hasattr(adapter, "close"):
        adapter.close()

    return report


# ============ CLI 入口 ============


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prompt Search — 自動迭代 system prompt / tool description 變體"
    )
    parser.add_argument(
        "--quick-only",
        action="store_true",
        help="只跑快速篩選（debug 用），不執行完整驗證",
    )
    parser.add_argument(
        "--dimensions",
        type=str,
        default="add_item_desc,query_menu_desc,system_rules",
        help=(
            "搜索維度（逗號分隔）。"
            f"可用: {','.join(DIMENSION_MAP.keys())}。"
            "預設: add_item_desc,query_menu_desc,system_rules"
        ),
    )
    parser.add_argument(
        "--hard-cases",
        type=str,
        default=None,
        help="指定 hard case IDs（逗號分隔），預設使用內建 7 個",
    )
    args = parser.parse_args()

    # 解析維度
    raw_dims = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    invalid_dims = [d for d in raw_dims if d not in DIMENSION_MAP]
    if invalid_dims:
        print(f"錯誤：不支援的維度 {invalid_dims}。可用: {list(DIMENSION_MAP.keys())}")
        sys.exit(1)

    # 解析 hard cases
    hard_cases: list[str] | None = None
    if args.hard_cases:
        hard_cases = [c.strip() for c in args.hard_cases.split(",") if c.strip()]

    run_prompt_search(
        dimensions=raw_dims,
        quick_only=args.quick_only,
        hard_case_ids=hard_cases,
    )


if __name__ == "__main__":
    main()
