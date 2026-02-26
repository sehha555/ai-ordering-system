"""
模型 Benchmark Runner
用法: python -m benchmarks.run_benchmark --type asr|tts|llm|e2e|all [--model MODEL_ID]
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml


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


def load_test_data(benchmark_type: str) -> list[dict]:
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
        with open(data_dir / "test_scenarios.json", "r", encoding="utf-8") as f:
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
            case_results.append({
                "success": False,
                "error": str(e),
                "latency": elapsed,
            })
    return {"case_id": case_id, "runs": case_results}


def run_single_benchmark(
    benchmark_type: str, model_config: dict, test_data: list, config: dict, workers: int = 1,
) -> dict:
    adapter = get_adapter(benchmark_type, model_config["adapter"], model_config.get("params", {}))
    repeat = config["benchmark"]["repeat"]
    timeout = config["benchmark"]["timeout"]

    # 暖機：先跑一次丟棄結果，避免冷啟動影響數據
    if test_data:
        try:
            print("    🔥 暖機中...", end="", flush=True)
            adapter.run(test_data[0], timeout=timeout)
            print(" 完成")
        except Exception:
            print(" 跳過")

    results = {
        "model_id": model_config["id"],
        "model_name": model_config["name"],
        "type": benchmark_type,
        "timestamp": datetime.now().isoformat(),
        "test_cases": [],
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
            status = "✓" if all(r["success"] for r in case_result["runs"]) else "✗"
            print(f" {status} {avg_lat:.1f}s")
            results["test_cases"].append(case_result)
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
                status = "✓" if all(r["success"] for r in runs) else "✗"
                print(f"    [{done_count}/{total}] {case_result['case_id']}... {status} {avg_lat:.1f}s")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_single_case, adapter, case, repeat, timeout): case
                for case in test_data
            }
            for future in as_completed(futures):
                case_result = future.result()
                _on_complete(case_result)
                results["test_cases"].append(case_result)

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
        results["summary"] = compute_llm_metrics(results["test_cases"], test_data)

    return results


def save_report(all_results: list[dict], benchmark_type: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"benchmark_{benchmark_type}_{timestamp}.json"

    report = {
        "benchmark_type": benchmark_type,
        "timestamp": datetime.now().isoformat(),
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

    print(f"\n{'='*60}")
    print(f"  {report['benchmark_type'].upper()} 模型比較")
    print(f"{'='*60}")

    all_metrics = set()
    for metrics in comp.values():
        all_metrics.update(metrics.keys())

    header = f"{'模型':<25}"
    for m in sorted(all_metrics):
        header += f"{m:<18}"
    print(header)
    print("-" * len(header))

    for model_id, metrics in comp.items():
        row = f"{model_id:<25}"
        for m in sorted(all_metrics):
            val = metrics.get(m, "N/A")
            if isinstance(val, float):
                row += f"{val:<18.4f}"
            else:
                row += f"{str(val):<18}"
        print(row)


def main():
    parser = argparse.ArgumentParser(description="模型 Benchmark Runner")
    parser.add_argument("--type", choices=["asr", "tts", "llm", "e2e", "all"], required=True)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 個測試案例")
    parser.add_argument("--fast", action="store_true", help="快速模式：repeat=1 + limit=20")
    parser.add_argument("--workers", type=int, default=None, help="平行 workers 數（預設讀 config）")
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

        test_data = load_test_data(btype)
        if not test_data:
            print(f"⚠️  {btype} 沒有測試資料，跳過")
            continue

        if args.limit and args.limit < len(test_data):
            test_data = test_data[:args.limit]

        mode_tag = " ⚡快速" if args.fast else ""
        worker_tag = f", {workers} workers" if workers > 1 else ""
        print(f"\n🚀 開始 {btype.upper()} benchmark ({len(models)} 個模型, {len(test_data)} 個測試案例{worker_tag}){mode_tag}")

        all_results = []
        for model in models:
            print(f"  ▶ 測試中: {model['name']}...")
            result = run_single_benchmark(btype, model, test_data, config, workers=workers)
            all_results.append(result)
            print("    ✅ 完成")

        report = save_report(all_results, btype, output_dir)
        print_comparison(report)


if __name__ == "__main__":
    main()
