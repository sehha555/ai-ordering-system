"""TTS 評估指標"""


def estimate_audio_duration(text: str, chars_per_second: float = 4.0) -> float:
    """根據文字長度估算語音時長（秒）

    中文語速約 4 字/秒（含標點）
    """
    return max(len(text) / chars_per_second, 0.5)


def compute_tts_metrics(test_cases: list[dict], test_data: list[dict] = None) -> dict:
    total_first_byte = 0.0
    total_time = 0.0
    total_audio_size = 0
    total_rtf = 0.0
    success_count = 0
    total_runs = 0

    # 建立 text 查找表
    text_map = {}
    if test_data:
        text_map = {d["id"]: d["text"] for d in test_data}

    for case in test_cases:
        case_text = text_map.get(case["case_id"], "")
        for run in case["runs"]:
            total_runs += 1
            if run["success"]:
                success_count += 1
                total_first_byte += run.get("first_byte_time", 0)
                gen_time = run.get("total_time", 0)
                total_time += gen_time
                audio = run.get("audio_bytes", b"")
                total_audio_size += len(audio) if isinstance(audio, bytes) else 0

                # RTF 計算
                audio_duration = run.get("audio_duration", 0)
                if not audio_duration and case_text:
                    audio_duration = estimate_audio_duration(case_text)
                if audio_duration > 0:
                    total_rtf += gen_time / audio_duration

    n = max(success_count, 1)
    return {
        "avg_first_byte_latency": total_first_byte / n,
        "avg_total_time": total_time / n,
        "avg_rtf": total_rtf / n,
        "avg_audio_size_kb": (total_audio_size / n) / 1024,
        "success_rate": success_count / max(total_runs, 1),
    }
