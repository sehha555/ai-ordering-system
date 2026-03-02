"""LLM 評估指標"""
from collections import Counter


def _arg_value_matches(expected_val: str, actual_val) -> bool:
    """參數值子串匹配 — expected 出現在 actual 中就算對"""
    if actual_val is None:
        return False
    return expected_val in str(actual_val)


def _match_args(expected_args: dict, actual_args: dict) -> bool:
    """子集匹配 — expected 中每個 key-value 都必須出現在 actual 中"""
    for key, expected_val in expected_args.items():
        actual_val = actual_args.get(key)
        if isinstance(expected_val, bool):
            # bool 精確匹配
            if actual_val is not expected_val and actual_val != expected_val:
                return False
        elif isinstance(expected_val, str):
            if not _arg_value_matches(expected_val, actual_val):
                return False
        else:
            # 數字等其他型別精確匹配
            if actual_val != expected_val:
                return False
    return True


def tool_call_match(
    actual_calls: list[dict],
    expected_tools: list[str],
    expected_args: list[dict] | None = None,
) -> dict:
    """計算工具呼叫的 Precision / Recall / F1，含參數驗證

    Args:
        actual_calls: 實際 tool calls [{"name": str, "arguments": dict}, ...]
        expected_tools: 預期 tool 名稱列表 ["add_to_cart", ...]
        expected_args: 預期參數列表 [{"name": str, "args": dict}, ...]
            若提供，會額外驗證參數正確率，最終 f1 = name_f1 * args_score

    Returns:
        {"precision": float, "recall": float, "f1": float, "args_score": float}
    """
    if not expected_tools:
        if not actual_calls:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "args_score": 1.0}
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0, "args_score": 1.0}

    # 用 Counter（multiset）計數，避免 set 去重導致 3 次 add_to_cart 被算成 1 次
    actual_counter = Counter(tc["name"] for tc in actual_calls)
    expected_counter = Counter(expected_tools)
    matched_count = sum((actual_counter & expected_counter).values())

    precision = matched_count / sum(actual_counter.values()) if actual_counter else 0.0
    recall = matched_count / sum(expected_counter.values())
    name_f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # 參數驗證
    args_score = 1.0
    if expected_args:
        # 貪心匹配：每個 expected 找 actual 中 name 相同且 args 命中的
        remaining_actual = list(actual_calls)
        matched_count = 0
        for exp in expected_args:
            exp_name = exp["name"]
            exp_args = exp.get("args", {})
            for i, act in enumerate(remaining_actual):
                if act["name"] == exp_name:
                    actual_arguments = act.get("arguments", {})
                    if _match_args(exp_args, actual_arguments):
                        matched_count += 1
                        remaining_actual.pop(i)
                        break
        args_score = matched_count / len(expected_args)

    f1 = name_f1 * args_score

    return {"precision": precision, "recall": recall, "f1": f1, "args_score": args_score}


def response_quality_check(response: str, expected_contains: list[str]) -> float:
    """檢查回應是否包含預期的關鍵詞

    Returns:
        包含率 (0.0 ~ 1.0)
    """
    if not expected_contains:
        return 1.0
    matched = sum(1 for kw in expected_contains if kw in response)
    return matched / len(expected_contains)


def _percentile(values: list[float], p: int) -> float:
    """計算百分位數（p=50 → 中位數）"""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = (len(sorted_v) - 1) * p / 100
    lo = int(idx)
    hi = min(lo + 1, len(sorted_v) - 1)
    frac = idx - lo
    return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac


def compute_llm_metrics(test_cases: list[dict], test_data: list[dict], pass_threshold: float = 0.8) -> dict:
    total_f1 = 0.0
    total_precision = 0.0
    total_recall = 0.0
    total_response_quality = 0.0
    total_tokens = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    success_count = 0
    timeout_count = 0
    error_count = 0
    total_runs = 0
    scenario_pass = 0
    scenario_total = 0

    latencies_all = []      # 所有 run 的延遲（含 timeout）
    latencies_success = []  # 成功 run 的延遲

    expected_map = {d["id"]: d for d in test_data}

    # 每案判定結果
    case_verdicts = []

    for case in test_cases:
        case_data = expected_map.get(case["case_id"], {})
        expected_tools = case_data.get("expected_tools", [])
        expected_contains = case_data.get("expected_response_contains", [])
        case_expected_args = case_data.get("expected_args", None)
        case_passed = False
        case_fail_reason = None

        for run in case["runs"]:
            total_runs += 1
            latencies_all.append(run["latency"])

            if run["success"]:
                success_count += 1
                latencies_success.append(run["latency"])
                total_tokens += run.get("tokens", 0)
                total_prompt_tokens += run.get("prompt_tokens", 0)
                total_completion_tokens += run.get("completion_tokens", 0)

                scores = tool_call_match(run.get("tool_calls", []), expected_tools, case_expected_args)
                total_f1 += scores["f1"]
                total_precision += scores["precision"]
                total_recall += scores["recall"]

                rq = response_quality_check(run.get("response", ""), expected_contains)
                total_response_quality += rq

                if scores["f1"] >= pass_threshold:
                    case_passed = True
                else:
                    case_fail_reason = f"tool_call_f1={scores['f1']:.2f} < {pass_threshold}"
            else:
                error_msg = run.get("error", "unknown")
                if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                    timeout_count += 1
                    case_fail_reason = "timeout"
                else:
                    error_count += 1
                    case_fail_reason = error_msg

        scenario_total += 1
        if case_passed:
            scenario_pass += 1

        case_verdicts.append({
            "case_id": case["case_id"],
            "passed": case_passed,
            "fail_reason": case_fail_reason if not case_passed else None,
        })

    n = max(success_count, 1)

    # tokens/sec（只算成功的 run）
    total_time_success = sum(latencies_success) if latencies_success else 1.0
    tokens_per_sec = total_completion_tokens / total_time_success if total_completion_tokens > 0 else 0.0

    return {
        # 延遲
        "avg_latency": sum(latencies_success) / n if latencies_success else 0.0,
        "latency_p50": _percentile(latencies_success, 50),
        "latency_p90": _percentile(latencies_success, 90),
        "latency_min": min(latencies_success) if latencies_success else 0.0,
        "latency_max": max(latencies_success) if latencies_success else 0.0,
        # Token 用量
        "avg_tokens": total_tokens / n,
        "avg_prompt_tokens": total_prompt_tokens / n,
        "avg_completion_tokens": total_completion_tokens / n,
        "tokens_per_sec": round(tokens_per_sec, 1),
        # 準確率
        "tool_call_f1": total_f1 / n,
        "tool_call_precision": total_precision / n,
        "tool_call_recall": total_recall / n,
        "response_quality": total_response_quality / n,
        # 通過率
        "scenario_pass_rate": scenario_pass / max(scenario_total, 1),
        "success_rate": success_count / max(total_runs, 1),
        "total_runs": total_runs,
        "success_count": success_count,
        "timeout_count": timeout_count,
        "error_count": error_count,
        # 每案判定
        "case_verdicts": case_verdicts,
    }
