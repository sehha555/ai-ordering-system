"""
模型 Benchmark Runner
用法: python -m benchmarks.run_benchmark --type asr|tts|llm|e2e|all [--model MODEL_ID]
"""
import argparse
import json
import time
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


def run_single_benchmark(benchmark_type: str, model_config: dict, test_data: list, config: dict) -> dict:
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

    for case in test_data:
        case_results = []
        for _ in range(repeat):
            try:
                start = time.perf_counter()
                result = adapter.run(case, timeout=timeout)
                elapsed = time.perf_counter() - start
                result["latency"] = elapsed
                result["success"] = True
                case_results.append(result)
            except Exception as e:
                case_results.append({
                    "success": False,
                    "error": str(e),
                    "latency": timeout,
                })

        results["test_cases"].append({
            "case_id": case.get("id", "unknown"),
            "runs": case_results,
        })

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
    args = parser.parse_args()

    config = load_config(Path(args.config) if args.config else None)
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

        print(f"\n🚀 開始 {btype.upper()} benchmark ({len(models)} 個模型, {len(test_data)} 個測試案例)")

        all_results = []
        for model in models:
            print(f"  ▶ 測試中: {model['name']}...")
            result = run_single_benchmark(btype, model, test_data, config)
            all_results.append(result)
            print(f"    ✅ 完成")

        report = save_report(all_results, btype, output_dir)
        print_comparison(report)


if __name__ == "__main__":
    main()
