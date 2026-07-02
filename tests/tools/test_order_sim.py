# tests/tools/test_order_sim.py
"""SSE 解析函式單元測試 — 不打網路，只測 parse_sse_line 和 _format_cart。"""

import importlib.util
from pathlib import Path

# 直接以絕對路徑載入 tools/order_sim.py，避免與 src/tools/ 套件名稱衝突
_module_path = Path(__file__).resolve().parents[2] / "tools" / "order_sim.py"
_spec = importlib.util.spec_from_file_location("order_sim", _module_path)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

parse_sse_line = _mod.parse_sse_line
_format_cart = _mod._format_cart


def _feed_lines(lines: list[str]) -> list[dict]:
    """餵一組行給 parse_sse_line，收集所有完整事件。"""
    state: dict = {"event": None, "data": None}
    events = []
    for line in lines:
        evt = parse_sse_line(line, state)
        if evt is not None:
            events.append(evt)
    return events


def test_parse_single_event():
    """標準單一事件：event 行 + data 行 + 空行觸發 dispatch。"""
    lines = ["event: text_delta", 'data: {"content": "你好"}', ""]
    events = _feed_lines(lines)
    assert len(events) == 1
    assert events[0]["event"] == "text_delta"
    assert events[0]["data"]["content"] == "你好"


def test_parse_multiple_events_in_sequence():
    """連續多個事件各自正確解析，state 在空行後重置。"""
    lines = [
        "event: transcription",
        'data: {"text": "我要飯糰"}',
        "",
        "event: cart_update",
        'data: {"items": [], "total": 0}',
        "",
    ]
    events = _feed_lines(lines)
    assert len(events) == 2
    assert events[0]["event"] == "transcription"
    assert events[0]["data"]["text"] == "我要飯糰"
    assert events[1]["event"] == "cart_update"


def test_audio_chunk_is_parsed_normally():
    """audio_chunk 事件本身可正常解析（略過邏輯在上層，不在 parse_sse_line）。"""
    lines = ["event: audio_chunk", 'data: {"chunk": "base64..."}', ""]
    events = _feed_lines(lines)
    assert len(events) == 1
    assert events[0]["event"] == "audio_chunk"


def test_malformed_json_data_does_not_crash():
    """data 欄位不是合法 JSON 時，解析結果放進 _raw，不拋例外。"""
    lines = ["event: error", "data: not-valid-json", ""]
    events = _feed_lines(lines)
    assert len(events) == 1
    assert "_raw" in events[0]["data"]
    assert events[0]["data"]["_raw"] == "not-valid-json"


def test_format_cart_empty_and_with_items():
    """空購物車顯示 (空)；有品項時含數量、金額；price_pending 顯示 [待確認]。"""
    assert _format_cart({"items": [], "total": 0}) == "cart: (空) | total $0"

    data = {
        "items": [
            {"name": "套餐C", "quantity": 1, "price": 130, "price_pending": False},
            {"name": "飯糰", "quantity": 2, "price": 0, "price_pending": True},
        ],
        "total": 130,
    }
    result = _format_cart(data)
    assert "套餐C x1 $130" in result
    assert "飯糰 x2 [待確認]" in result
    assert "total $130" in result
