"""
模型 Benchmark Runner
用法: python -m benchmarks.run_benchmark --type asr|tts|llm|e2e|all [--model MODEL_ID]
      --resume: 從上次中斷處繼續跑
"""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml


def _checkpoint_path(output_dir: Path, benchmark_type: str, model_id: str) -> Path:
    return output_dir / f"checkpoint_{benchmark_type}_{model_id}.json"


def _load_checkpoint(path: Path) -> list[dict]:
    """載入 checkpoint，回傳已完成的 test_cases"""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_checkpoint(path: Path, completed_cases: list[dict]) -> None:
    """每完成一個 case 就寫入 checkpoint（原子寫入：先 .tmp 再 rename，避免 Ctrl+C 寫到一半損壞）"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(completed_cases, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_config(config_path: Path = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_adapter(adapter_type: str, adapter_name: str, params: dict):
    if adapter_type == "asr":
        from benchmarks.adapters.asr_adapters import create_asr_adapter

        return create_asr_adapter(adapter_name, params)
    elif adapter_type == "tts":
        from benchmarks.adapters.tts_adapters import create_tts_adapter

        return create_tts_adapter(adapter_name, params)
    elif adapter_type == "llm":
        from benchmarks.adapters.llm_adapters import create_llm_adapter

        return create_llm_adapter(adapter_name, params)
    else:
        raise ValueError(f"不支援的 adapter 類型: {adapter_type}")


def load_test_data(benchmark_type: str, scenarios: str | None = None) -> list[dict]:
    data_dir = Path(__file__).parent / "test_data" / benchmark_type
    if benchmark_type == "asr":
        manifest = data_dir / "manifest.json"
        if manifest.exists():
            with open(manifest, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    elif benchmark_type == "tts":
        with open(data_dir / "test_sentences.json", "r", encoding="utf-8") as f:
            return json.load(f)
    elif benchmark_type == "llm":
        # --scenarios <name> → test_scenarios_<name>.json，未指定 → test_scenarios.json
        filename = f"test_scenarios_{scenarios}.json" if scenarios else "test_scenarios.json"
        with open(data_dir / filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _run_single_case(adapter, case: dict, repeat: int, timeout: int) -> dict:
    """執行單一測試案例（含重複次數），回傳 case_id + runs 結果。"""
    case_id = case.get("id", "unknown")
    case_results = []
    for _ in range(repeat):
        start = time.perf_counter()
        try:
            result = adapter.run(case, timeout=timeout)
            elapsed = time.perf_counter() - start
            result["latency"] = elapsed
            result["success"] = True
            case_results.append(result)
        except Exception as e:
            elapsed = time.perf_counter() - start
            case_results.append(
                {
                    "success": False,
                    "error": str(e),
                    "latency": elapsed,
                }
            )
    return {"case_id": case_id, "runs": case_results}


def run_single_benchmark(
    benchmark_type: str,
    model_config: dict,
    test_data: list,
    config: dict,
    workers: int = 1,
    resume: bool = False,
    output_dir: Path | None = None,
) -> dict:
    adapter = get_adapter(benchmark_type, model_config["adapter"], model_config.get("params", {}))
    repeat = config["benchmark"]["repeat"]
    timeout = config["benchmark"]["timeout"]

    # Checkpoint: 載入已完成的 cases
    ckpt_path = _checkpoint_path(
        output_dir or Path(__file__).parent / config["benchmark"]["output_dir"],
        benchmark_type,
        model_config["id"],
    )
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    resumed_cases: list[dict] = []
    if resume:
        resumed_cases = _load_checkpoint(ckpt_path)
        if resumed_cases:
            done_ids = {c["case_id"] for c in resumed_cases}
            before = len(test_data)
            test_data = [d for d in test_data if d["id"] not in done_ids]
            print(f"    -- resume: {len(done_ids)} 已完成，剩 {len(test_data)}/{before}")

    # 暖機：先跑一次丟棄結果，避免冷啟動影響數據
    if test_data:
        try:
            print("    -- warmup...", end="", flush=True)
            adapter.run(test_data[0], timeout=timeout)
            print(" ok")
        except Exception:
            print(" skip")

    results = {
        "model_id": model_config["id"],
        "model_name": model_config["name"],
        "type": benchmark_type,
        "timestamp": datetime.now().isoformat(),
        "test_cases": resumed_cases,
        "summary": {},
    }

    total = len(test_data)
    bench_start = time.perf_counter()

    if workers <= 1:
        # 序列模式（原始行為）
        for idx, case in enumerate(test_data, 1):
            case_id = case.get("id", "unknown")
            print(f"    [{idx}/{total}] {case_id}...", end="", flush=True)
            case_result = _run_single_case(adapter, case, repeat, timeout)
            avg_lat = sum(r["latency"] for r in case_result["runs"]) / len(case_result["runs"])
            status = "v" if all(r["success"] for r in case_result["runs"]) else "x"
            print(f" {status} {avg_lat:.1f}s")
            results["test_cases"].append(case_result)
            _save_checkpoint(ckpt_path, results["test_cases"])
    else:
        # 平行模式
        done_count = 0
        print_lock = threading.Lock()

        def _on_complete(case_result: dict):
            nonlocal done_count
            with print_lock:
                done_count += 1
                runs = case_result["runs"]
                avg_lat = sum(r["latency"] for r in runs) / len(runs)
                status = "v" if all(r["success"] for r in runs) else "x"
                print(
                    f"    [{done_count}/{total}] {case_result['case_id']}... {status} {avg_lat:.1f}s"
                )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_single_case, adapter, case, repeat, timeout): case
                for case in test_data
            }
            for future in as_completed(futures):
                case_result = future.result()
                _on_complete(case_result)
                results["test_cases"].append(case_result)
                _save_checkpoint(ckpt_path, results["test_cases"])

    # 釋放 adapter 資源（如 httpx.Client 連線池）
    if hasattr(adapter, "close"):
        adapter.close()

    bench_elapsed = time.perf_counter() - bench_start
    mode = f"平行 ×{workers}" if workers > 1 else "序列"
    print(f"    ⏱  {total} 案例完成，耗時 {bench_elapsed:.1f}s（{mode}）")

    # 計算 metrics
    if benchmark_type == "asr":
        from benchmarks.metrics.asr_metrics import compute_asr_metrics

        results["summary"] = compute_asr_metrics(results["test_cases"], test_data)
    elif benchmark_type == "tts":
        from benchmarks.metrics.tts_metrics import compute_tts_metrics

        results["summary"] = compute_tts_metrics(results["test_cases"], test_data)
    elif benchmark_type == "llm":
        from benchmarks.metrics.llm_metrics import compute_llm_metrics

        # allow_clarification 是 metric 設定，放 model_config 頂層而非 adapter params
        allow_clarification = model_config.get("allow_clarification", False)
        results["summary"] = compute_llm_metrics(
            results["test_cases"], test_data, allow_clarification=allow_clarification
        )

    # 全部跑完，清除 checkpoint
    ckpt_path.unlink(missing_ok=True)

    return results


def _collect_env_info() -> dict:
    """收集執行環境資訊（GPU、模型載入狀態等）"""
    import subprocess

    env = {}
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        ).strip()
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 4:
            env["gpu"] = {
                "name": parts[0],
                "vram_total_mb": int(parts[1]),
                "vram_used_mb": int(parts[2]),
                "vram_free_mb": int(parts[3]),
            }
    except Exception:
        pass
    try:
        out = subprocess.check_output(["ollama", "ps"], text=True, timeout=5).strip()
        env["ollama_ps"] = out
    except Exception:
        pass
    return env


def save_report(all_results: list[dict], benchmark_type: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"benchmark_{benchmark_type}_{timestamp}.json"

    report = {
        "benchmark_type": benchmark_type,
        "timestamp": datetime.now().isoformat(),
        "environment": _collect_env_info(),
        "results": all_results,
        "comparison": generate_comparison(all_results),
    }

    def _json_default(obj):
        """處理無法序列化的型別（如 bytes）"""
        if isinstance(obj, bytes):
            return f"<bytes:{len(obj)}>"
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_json_default)

    print(f"\n📊 報告已儲存: {report_path}")
    return report


def generate_comparison(results: list[dict]) -> dict:
    comparison = {}
    for r in results:
        comparison[r["model_id"]] = r["summary"]
    return comparison


def print_comparison(report: dict):
    comp = report["comparison"]
    if not comp:
        return

    # 環境資訊
    env = report.get("environment", {})
    if env.get("gpu"):
        gpu = env["gpu"]
        print(
            f"\n  GPU: {gpu['name']} | VRAM: {gpu['vram_used_mb']}/{gpu['vram_total_mb']} MB ({gpu['vram_free_mb']} MB free)"
        )
    if env.get("ollama_ps"):
        for line in env["ollama_ps"].split("\n")[1:]:  # 跳過 header
            if line.strip():
                print(f"  Ollama: {line.strip()}")

    print(f"\n{'=' * 70}")
    print(f"  {report['benchmark_type'].upper()} Benchmark 結果")
    print(f"{'=' * 70}")

    for model_id, metrics in comp.items():
        print(f"\n  模型: {model_id}")
        print(f"  {'─' * 50}")

        # 通過率 + 成功率
        pass_rate = metrics.get("scenario_pass_rate", 0)
        success = metrics.get("success_count", 0)
        total = metrics.get("total_runs", 0)
        timeouts = metrics.get("timeout_count", 0)
        errors = metrics.get("error_count", 0)
        print(f"  通過率:  {pass_rate:.0%} ({int(pass_rate * total)}/{total})")
        print(f"  成功率:  {success}/{total} | Timeout: {timeouts} | Error: {errors}")

        # 延遲
        print(
            f"  延遲:    avg={metrics.get('avg_latency', 0):.1f}s | p50={metrics.get('latency_p50', 0):.1f}s | p90={metrics.get('latency_p90', 0):.1f}s | min={metrics.get('latency_min', 0):.1f}s | max={metrics.get('latency_max', 0):.1f}s"
        )

        # Token
        print(
            f"  Token:   prompt={metrics.get('avg_prompt_tokens', 0):.0f} | completion={metrics.get('avg_completion_tokens', 0):.0f} | total={metrics.get('avg_tokens', 0):.0f} | {metrics.get('tokens_per_sec', 0):.1f} tok/s"
        )

        # 準確率
        print(
            f"  Tool F1: {metrics.get('tool_call_f1', 0):.2f} (P={metrics.get('tool_call_precision', 0):.2f} R={metrics.get('tool_call_recall', 0):.2f})"
        )

        # 每案判定
        verdicts = metrics.get("case_verdicts", [])
        if verdicts:
            failed = [v for v in verdicts if not v["passed"]]
            if failed:
                print(f"\n  失敗案例 ({len(failed)}):")
                for v in failed:
                    reason = v.get("fail_reason", "unknown")
                    print(f"    ✗ {v['case_id']}: {reason}")


def main():
    parser = argparse.ArgumentParser(description="模型 Benchmark Runner")
    parser.add_argument("--type", choices=["asr", "tts", "llm", "e2e", "all"], required=True)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 個測試案例")
    parser.add_argument("--fast", action="store_true", help="快速模式：repeat=1 + limit=20")
    parser.add_argument(
        "--workers", type=int, default=None, help="平行 workers 數（預設讀 config）"
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=None,
        help="指定 scenario 檔案名後綴（不含路徑和 .json），如 'v2' → test_scenarios_v2.json",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="從上次中斷處繼續跑（讀取 checkpoint）",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config) if args.config else None)

    # --fast：自動 repeat=1 + limit=20（不覆蓋使用者明確指定的值）
    if args.fast:
        config["benchmark"]["repeat"] = 1
        if args.limit is None:
            args.limit = 20

    # workers 優先順序：CLI --workers > config concurrency > 預設 1
    workers = args.workers or config["benchmark"].get("concurrency", 1)

    benchmark_types = ["asr", "tts", "llm", "e2e"] if args.type == "all" else [args.type]
    output_dir = Path(__file__).parent / config["benchmark"]["output_dir"]

    for btype in benchmark_types:
        if btype not in config:
            print(f"⚠️  配置中沒有 {btype} 的設定，跳過")
            continue

        models = config[btype]["models"]
        if args.model:
            models = [m for m in models if m["id"] == args.model]
            if not models:
                print(f"⚠️  找不到模型 {args.model}，跳過")
                continue

        test_data = load_test_data(btype, getattr(args, "scenarios", None))
        if not test_data:
            print(f"⚠️  {btype} 沒有測試資料，跳過")
            continue

        if args.limit and args.limit < len(test_data):
            test_data = test_data[: args.limit]

        mode_tag = " ⚡快速" if args.fast else ""
        worker_tag = f", {workers} workers" if workers > 1 else ""
        print(
            f"\n🚀 開始 {btype.upper()} benchmark ({len(models)} 個模型, {len(test_data)} 個測試案例{worker_tag}){mode_tag}"
        )

        all_results = []
        for model in models:
            print(f"  ▶ 測試中: {model['name']}...")
            result = run_single_benchmark(
                btype,
                model,
                test_data,
                config,
                workers=workers,
                resume=args.resume,
                output_dir=output_dir,
            )
            all_results.append(result)
            print("    ✅ 完成")

        report = save_report(all_results, btype, output_dir)
        print_comparison(report)


if __name__ == "__main__":
    main()
