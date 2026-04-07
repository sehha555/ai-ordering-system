"""快速新增 benchmark 場景的 CLI 工具。

用法：
    uv run python -m benchmarks.add_scenario --id <id> --input <text> [選項]
"""

import argparse
import json
import sys
from pathlib import Path

# 預設目標檔案
DEFAULT_FILE = Path(__file__).parent / "test_data" / "llm" / "test_scenarios.json"


def parse_expect_arg(raw: str) -> dict:
    """解析 --expect-arg 格式：tool_name:key=value。

    Args:
        raw: 原始字串，例如 "add_item:name=玉米"

    Returns:
        {"name": "add_item", "args": {"name": "玉米"}}

    Raises:
        ValueError: 格式不符合 tool_name:key=value
    """
    if ":" not in raw:
        raise ValueError(f"--expect-arg 格式錯誤（需含 ':'）：{raw!r}")
    tool_part, kv_part = raw.split(":", 1)
    if "=" not in kv_part:
        raise ValueError(f"--expect-arg 格式錯誤（需含 '='）：{raw!r}")
    key, value = kv_part.split("=", 1)
    return {"name": tool_part.strip(), "args": {key.strip(): value.strip()}}


def parse_history(raw: str) -> list[dict]:
    """解析 --history JSON 字串為訊息列表。

    Args:
        raw: JSON 字串，例如 '[{"role":"user","content":"你好"}]'

    Returns:
        解析後的 list[dict]

    Raises:
        ValueError: JSON 格式錯誤
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--history JSON 解析失敗：{exc}") from exc
    if not isinstance(data, list):
        raise ValueError("--history 必須是 JSON 陣列")
    return data


def build_scenario(args: argparse.Namespace) -> dict:
    """根據 CLI 參數組建場景 dict。

    Args:
        args: argparse 解析結果

    Returns:
        符合 test_scenarios.json 格式的場景 dict
    """
    # 組建訊息列表：先放前置對話，再放本次使用者輸入
    messages: list[dict] = []
    if args.history:
        messages.extend(parse_history(args.history))
    messages.append({"role": "user", "content": args.input})

    # 解析 expected_args
    expected_args: list[dict] = []
    for raw in args.expect_arg or []:
        expected_args.append(parse_expect_arg(raw))

    # 決定 expected_tools：若明確給 --expect-no-tool 或沒有 --expect-tool 且沒有 --expect-arg 則為空
    if args.expect_no_tool:
        expected_tools: list[str] = []
    else:
        expected_tools = list(args.expect_tool or [])

    scenario: dict = {
        "id": args.id,
        "description": args.desc or "",
        "category": args.category,
        "messages": messages,
        "expected_tools": expected_tools,
        "expected_args": expected_args,
        "expected_response_contains": list(args.expect_contains or []),
        "expected_behavior": args.behavior or "",
    }
    return scenario


def load_scenarios(path: Path) -> list[dict]:
    """從檔案讀取場景列表。

    Args:
        path: JSON 檔案路徑

    Returns:
        場景列表
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def save_scenarios(path: Path, scenarios: list[dict]) -> None:
    """將場景列表寫回檔案（UTF-8 + indent=2）。

    Args:
        path: 目標 JSON 檔案路徑
        scenarios: 場景列表
    """
    path.write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="快速新增 benchmark 場景到 test_scenarios.json")
    parser.add_argument("--id", required=True, help="場景 ID（唯一）")
    parser.add_argument("--desc", default="", help="場景描述")
    parser.add_argument("--category", default="edge_case", help="分類（預設 edge_case）")
    parser.add_argument("--input", required=True, help="使用者輸入文字")
    parser.add_argument("--history", default=None, help="前置對話 JSON 字串（多輪用）")
    parser.add_argument(
        "--expect-tool",
        dest="expect_tool",
        action="append",
        metavar="TOOL",
        help="預期工具名（可重複）",
    )
    parser.add_argument(
        "--expect-arg",
        dest="expect_arg",
        action="append",
        metavar="TOOL:KEY=VALUE",
        help="預期參數，格式 tool_name:key=value（可重複）",
    )
    parser.add_argument(
        "--expect-contains",
        dest="expect_contains",
        action="append",
        metavar="KEYWORD",
        help="預期回覆包含的關鍵字（可重複）",
    )
    parser.add_argument(
        "--expect-no-tool",
        dest="expect_no_tool",
        action="store_true",
        help="預期不 call 任何 tool",
    )
    parser.add_argument("--behavior", default="", help="預期行為描述")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_FILE),
        help="目標 JSON 檔（預設 test_scenarios.json）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只印出新場景，不寫入檔案",
    )

    args = parser.parse_args()
    target = Path(args.file)

    # 建立新場景
    try:
        new_scenario = build_scenario(args)
    except ValueError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        sys.exit(1)

    # 讀取現有場景並檢查 ID 重複
    scenarios = load_scenarios(target)
    existing_ids = {s["id"] for s in scenarios}
    if new_scenario["id"] in existing_ids:
        print(f"錯誤：ID {new_scenario['id']!r} 已存在", file=sys.stderr)
        sys.exit(1)

    # 印出新場景
    print(json.dumps(new_scenario, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n（dry-run 模式，未寫入檔案）")
        return

    # Append 並寫回
    scenarios.append(new_scenario)
    save_scenarios(target, scenarios)
    print(f"\n已寫入 {target}，目前共 {len(scenarios)} 個場景")


if __name__ == "__main__":
    main()
