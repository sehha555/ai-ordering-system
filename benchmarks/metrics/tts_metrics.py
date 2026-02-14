"""TTS 評估指標"""


def compute_tts_metrics(test_cases: list[dict]) -> dict:
    total_first_byte = 0.0
    total_time = 0.0
    total_audio_size = 0
    success_count = 0
    total_runs = 0

    for case in test_cases:
        for run in case["runs"]:
            total_runs += 1
            if run["success"]:
                success_count += 1
                total_first_byte += run.get("first_byte_time", 0)
                total_time += run.get("total_time", 0)
                audio = run.get("audio_bytes", b"")
                total_audio_size += len(audio) if isinstance(audio, bytes) else 0

    n = max(success_count, 1)
    return {
        "avg_first_byte_latency": total_first_byte / n,
        "avg_total_time": total_time / n,
        "avg_audio_size_kb": (total_audio_size / n) / 1024,
        "success_rate": success_count / max(total_runs, 1),
    }
