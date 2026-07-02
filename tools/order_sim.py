#!/usr/bin/env python
# tools/order_sim.py
"""模擬點餐 CLI 工具 — 直接打 /api/text-chat SSE 端點，跳過語音辨識。"""

import argparse
import json
import sys
import uuid

import httpx

DEFAULT_BASE = "http://localhost:8001"


def parse_sse_line(line: str, state: dict) -> dict | None:
    """
    解析一行 SSE 文字，更新 state（mutable），事件完整時回傳 dict，否則回傳 None。

    state 結構：{"event": str|None, "data": Any}
    SSE 格式：event: 行設定名稱，data: 行設定資料，空行觸發 dispatch。
    """
    if line.startswith("event:"):
        state["event"] = line[6:].strip()
        return None
    if line.startswith("data:"):
        raw = line[5:].strip()
        try:
            state["data"] = json.loads(raw)
        except json.JSONDecodeError:
            state["data"] = {"_raw": raw}
        return None
    if line == "" and state.get("event"):
        # 空行代表事件結束，dispatch 並重置 state
        evt = {"event": state["event"], "data": state.get("data")}
        state["event"] = None
        state["data"] = None
        return evt
    return None


def _format_cart(cart_data: dict) -> str:
    """將 cart_update 事件的資料格式化為可讀字串。"""
    items = cart_data.get("items", [])
    total = cart_data.get("total", 0)
    if not items:
        return f"cart: (空) | total ${total}"
    parts = []
    for item in items:
        name = item.get("name", "?")
        qty = item.get("quantity", 1)
        if item.get("price_pending"):
            parts.append(f"{name} x{qty} [待確認]")
        else:
            price = item.get("price", 0)
            parts.append(f"{name} x{qty} ${price}")
    return f"cart: {', '.join(parts)} | total ${total}"


def _send_turn(
    client: httpx.Client, base: str, session_id: str, text: str, show_events: bool
) -> None:
    """送出一輪對話，解析 SSE 串流並印出結果。"""
    url = f"{base}/api/text-chat"
    payload = {"text": text, "session_id": session_id}

    print(f">> {text}")

    ai_reply_parts: list[str] = []
    cart_line = "cart: (空) | total $0"
    order_line: str | None = None
    audio_skip_count = 0
    state: dict = {"event": None, "data": None}

    try:
        with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                print(f"[錯誤] HTTP {resp.status_code}", file=sys.stderr)
                sys.exit(1)
            for line in resp.iter_lines():
                evt = parse_sse_line(line, state)
                if evt is None:
                    continue
                name = evt["event"]
                data = evt.get("data") or {}

                if name == "audio_chunk":
                    # 音訊資料略過，僅計數（避免大量 base64 洗屏）
                    audio_skip_count += 1
                    continue

                if show_events:
                    print(f"  [{name}] {json.dumps(data, ensure_ascii=False)}")

                if name == "text_delta":
                    ai_reply_parts.append(data.get("text", ""))
                elif name == "tts_text":
                    # tts_text 是完整 AI 回覆，取代已累積的 text_delta 片段
                    ai_reply_parts = [data.get("text", "")]
                elif name == "cart_update":
                    cart_line = _format_cart(data)
                elif name == "order_complete":
                    order_num = data.get("order_number", "")
                    order_total = data.get("total", 0)
                    order_line = f"order: {order_num}號 total ${order_total}"
                elif name == "error":
                    print(f"[錯誤] {data.get('message', data)}", file=sys.stderr)
    except httpx.ConnectError:
        print(f"[錯誤] 無法連線到 {base}，請確認後端跑在 port 8001", file=sys.stderr)
        sys.exit(1)

    if show_events and audio_skip_count:
        print(f"  [audio_chunk skipped x{audio_skip_count}]")

    ai_reply = "".join(ai_reply_parts).strip()
    if ai_reply:
        print(f"AI: {ai_reply}")
    print(cart_line)
    if order_line:
        print(order_line)
    print()  # 輪次間空行


def _run(args: argparse.Namespace) -> None:
    session_id = args.session or f"sim-{uuid.uuid4().hex[:8]}"

    # 單一 client 供多輪重用連線；LLM 慢速輪 + TTS cache miss 可達 30-40s，
    # timeout 放寬避免中斷後端 pipeline 汙染 session
    with httpx.Client(timeout=120) as client:
        if args.text:
            _send_turn(client, args.base, session_id, args.text, args.show_events)
        elif args.script:
            with open(args.script, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    _send_turn(client, args.base, session_id, line, args.show_events)
        else:  # --interactive
            print(f"模擬點餐（session={session_id}），輸入 exit 結束")
            while True:
                try:
                    text = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if text.lower() in ("exit", "quit"):
                    break
                if not text:
                    continue
                _send_turn(client, args.base, session_id, text, args.show_events)


def main() -> None:
    parser = argparse.ArgumentParser(description="模擬點餐 CLI — 打 /api/text-chat")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--text", help="單句輸入")
    mode.add_argument("--script", help="腳本檔路徑（UTF-8，一行一輪）")
    mode.add_argument("--interactive", action="store_true", help="互動式 REPL")
    parser.add_argument("--session", help="Session ID（預設自動產生）")
    parser.add_argument(
        "--base", default=DEFAULT_BASE, help=f"後端 base URL（預設 {DEFAULT_BASE}）"
    )
    parser.add_argument("--show-events", action="store_true", help="印出每個原始 SSE 事件")
    args = parser.parse_args()
    _run(args)


if __name__ == "__main__":
    main()
