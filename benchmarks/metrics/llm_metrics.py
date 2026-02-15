"""LLM 評估指標"""


def tool_call_match(actual_calls: list[dict], expected_tools: list[str]) -> dict:
    """計算工具呼叫的 Precision / Recall / F1

    Returns:
        {"precision": float, "recall": float, "f1": float}
    """
    if not expected_tools:
        if not actual_calls:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0}

    actual_names = {tc["name"] for tc in actual_calls}
    expected_set = set(expected_tools)
    matched = actual_names & expected_set

    precision = len(matched) / len(actual_names) if actual_names else 0.0
    recall = len(matched) / len(expected_set)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def response_quality_check(response: str, expected_contains: list[str]) -> float:
    """檢查回應是否包含預期的關鍵詞

    Returns:
        包含率 (0.0 ~ 1.0)
    """
    if not expected_contains:
        return 1.0
    matched = sum(1 for kw in expected_contains if kw in response)
    return matched / len(expected_contains)


def compute_llm_metrics(test_cases: list[dict], test_data: list[dict], pass_threshold: float = 0.8) -> dict:
    total_latency = 0.0
    total_f1 = 0.0
    total_precision = 0.0
    total_recall = 0.0
    total_response_quality = 0.0
    total_tokens = 0
    success_count = 0
    total_runs = 0
    scenario_pass = 0
    scenario_total = 0

    expected_map = {d["id"]: d for d in test_data}

    for case in test_cases:
        case_data = expected_map.get(case["case_id"], {})
        expected_tools = case_data.get("expected_tools", [])
        expected_contains = case_data.get("expected_response_contains", [])
        case_passed = False

        for run in case["runs"]:
            total_runs += 1
            if run["success"]:
                success_count += 1
                total_latency += run["latency"]
                total_tokens += run.get("tokens", 0)

                scores = tool_call_match(run.get("tool_calls", []), expected_tools)
                total_f1 += scores["f1"]
                total_precision += scores["precision"]
                total_recall += scores["recall"]

                rq = response_quality_check(run.get("response", ""), expected_contains)
                total_response_quality += rq

                if scores["f1"] >= pass_threshold:
                    case_passed = True

        scenario_total += 1
        if case_passed:
            scenario_pass += 1

    n = max(success_count, 1)
    return {
        "avg_latency": total_latency / n,
        "avg_tokens": total_tokens / n,
        "tool_call_f1": total_f1 / n,
        "tool_call_precision": total_precision / n,
        "tool_call_recall": total_recall / n,
        "response_quality": total_response_quality / n,
        "scenario_pass_rate": scenario_pass / max(scenario_total, 1),
    }
