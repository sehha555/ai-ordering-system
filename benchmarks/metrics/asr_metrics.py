"""ASR 評估指標"""


def char_error_rate(hypothesis: str, reference: str) -> float:
    """計算字元錯誤率 (CER) — Levenshtein distance"""
    ref_chars = list(reference)
    hyp_chars = list(hypothesis)
    r_len = len(ref_chars)
    h_len = len(hyp_chars)

    d = [[0] * (h_len + 1) for _ in range(r_len + 1)]
    for i in range(r_len + 1):
        d[i][0] = i
    for j in range(h_len + 1):
        d[0][j] = j

    for i in range(1, r_len + 1):
        for j in range(1, h_len + 1):
            if ref_chars[i - 1] == hyp_chars[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + 1)

    return d[r_len][h_len] / max(r_len, 1)


def compute_asr_metrics(test_cases: list[dict], test_data: list[dict]) -> dict:
    total_cer = 0.0
    total_latency = 0.0
    success_count = 0
    total_runs = 0

    ground_truth_map = {d["id"]: d["ground_truth"] for d in test_data}

    for case in test_cases:
        gt = ground_truth_map.get(case["case_id"], "")
        for run in case["runs"]:
            total_runs += 1
            if run["success"]:
                success_count += 1
                total_cer += char_error_rate(run.get("text", ""), gt)
                total_latency += run["latency"]

    n = max(success_count, 1)
    return {
        "avg_cer": total_cer / n,
        "avg_latency": total_latency / n,
        "success_rate": success_count / max(total_runs, 1),
    }
