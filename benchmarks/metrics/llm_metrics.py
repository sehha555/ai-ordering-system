"""LLM 評估指標"""


def tool_call_match(actual_calls: list[dict], expected_tools: list[str]) -> float:
    if not expected_tools:
        return 1.0 if not actual_calls else 0.0

    actual_names = {tc["name"] for tc in actual_calls}
    expected_set = set(expected_tools)
    matched = actual_names & expected_set
    return len(matched) / len(expected_set)


def compute_llm_metrics(test_cases: list[dict], test_data: list[dict]) -> dict:
    total_latency = 0.0
    total_tool_accuracy = 0.0
    total_tokens = 0
    success_count = 0
    total_runs = 0
    scenario_pass = 0
    scenario_total = 0

    expected_map = {d["id"]: d.get("expected_tools", []) for d in test_data}

    for case in test_cases:
        expected = expected_map.get(case["case_id"], [])
        case_passed = False

        for run in case["runs"]:
            total_runs += 1
            if run["success"]:
                success_count += 1
                total_latency += run["latency"]
                total_tokens += run.get("tokens", 0)
                accuracy = tool_call_match(run.get("tool_calls", []), expected)
                total_tool_accuracy += accuracy
                if accuracy >= 0.8:
                    case_passed = True

        scenario_total += 1
        if case_passed:
            scenario_pass += 1

    n = max(success_count, 1)
    return {
        "avg_latency": total_latency / n,
        "avg_tokens": total_tokens / n,
        "tool_call_accuracy": total_tool_accuracy / n,
        "scenario_pass_rate": scenario_pass / max(scenario_total, 1),
    }
