"""SSE 整合測試 — 驗證 /api/text-chat 和 /api/voice-chat 的事件序列

Mock 策略：
- DM 層（StreamingDMAdapter.process_input_stream）→ yield 預定義事件
- TTS 快取 → 所有文字命中，返回假 MP3 bytes
- voice-chat 額外 mock StreamingOrchestrator.process_audio_stream_v2（跳過 ASR/ffmpeg）
"""

import pytest
import json
import base64
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.services.streaming_orchestrator import StreamingOrchestrator

# ── helpers ──

FAKE_AUDIO = b"\xff\xfb\x90\x00" * 10  # 假 MP3 bytes


def parse_sse_events(text: str) -> list[dict]:
    """解析 SSE response body 為事件列表 [{event, data}, ...]"""
    events = []
    current_event = None
    current_data = None
    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            raw = line[6:]
            try:
                current_data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                current_data = raw
        elif line.strip() == "" and current_event is not None:
            events.append({"event": current_event, "data": current_data})
            current_event = None
            current_data = None
    return events


def event_types(events: list[dict]) -> list[str]:
    """取得事件類型列表"""
    return [e["event"] for e in events]


def find_event(events: list[dict], name: str) -> dict | None:
    """找到第一個匹配的事件"""
    return next((e for e in events if e["event"] == name), None)


def _dm_mock(events: list[dict]):
    """建立 DM process_input_stream mock，yield 預定義事件序列"""

    async def _gen(self, text):
        for evt in events:
            yield evt

    return _gen


# ── fixtures ──


@pytest.fixture
def client():
    from src.api.app import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_tts_cache():
    """TTS 快取永遠命中 → 跳過真實 TTS 合成"""
    with patch("src.services.streaming_orchestrator.tts_cache") as mc:
        mc.get.return_value = FAKE_AUDIO
        yield mc


# ── text-chat 測試 ──


class TestTextChatSSE:
    """POST /api/text-chat SSE 事件序列驗證"""

    def test_simple_reply_event_sequence(self, client):
        """簡單回覆：thinking → transcription → audio_chunk → tts_text → cart_update"""
        dm_events = [
            {"type": "text_delta", "content": "好的，還需要什麼嗎？"},
            {
                "type": "done",
                "cart": [],
                "order_payload": {"total_price": 0},
                "finalize_result": None,
                "preview_result": None,
            },
        ]
        with patch(
            "src.api.voice_router.StreamingDMAdapter.process_input_stream",
            _dm_mock(dm_events),
        ):
            r = client.post("/api/text-chat", json={"text": "你好", "session_id": "t-001"})

        assert r.status_code == 200
        events = parse_sse_events(r.text)
        types = event_types(events)

        # 事件順序驗證
        assert types[0] == "thinking"
        assert types[1] == "transcription"
        assert "audio_chunk" in types
        assert "tts_text" in types
        assert types[-1] == "cart_update"

        # transcription 回顯輸入文字
        trans = find_event(events, "transcription")
        assert trans["data"]["text"] == "你好"

    def test_tool_call_adds_status_event(self, client):
        """tool call → 多出 status 事件 + early_tts 產生 audio_chunk"""
        dm_events = [
            {
                "type": "tool_call",
                "tool_call": {"function": {"name": "add_to_cart", "arguments": "{}"}},
                "tool_result": {"ok": True},
            },
            {"type": "early_tts", "content": "好，一個薯餅～還要什麼？"},
            {
                "type": "done",
                "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
                "order_payload": {"total_price": 25},
                "finalize_result": None,
                "preview_result": None,
            },
        ]
        with patch(
            "src.api.voice_router.StreamingDMAdapter.process_input_stream",
            _dm_mock(dm_events),
        ):
            r = client.post("/api/text-chat", json={"text": "我要一個薯餅", "session_id": "t-002"})

        events = parse_sse_events(r.text)
        types = event_types(events)

        # status 事件存在且內容正確
        assert "status" in types
        status = find_event(events, "status")
        assert status["data"]["message"] == "正在加入購物車..."

        # early_tts 觸發 audio_chunk
        assert "audio_chunk" in types

        # cart_update 包含品項
        cart = find_event(events, "cart_update")
        assert cart["data"]["total"] == 25
        assert len(cart["data"]["items"]) == 1

    def test_error_yields_sse_error_event(self, client):
        """DM 層拋異常 → _sse_wrap 捕捉 → SSE error 事件"""

        async def _boom(self, text):
            raise RuntimeError("LLM 連線逾時")
            yield  # unreachable — 使 Python 將此函式視為 async generator

        with patch("src.api.voice_router.StreamingDMAdapter.process_input_stream", _boom):
            r = client.post("/api/text-chat", json={"text": "你好", "session_id": "t-003"})

        assert r.status_code == 200  # SSE 端點始終 200，錯誤在 event 裡
        events = parse_sse_events(r.text)
        types = event_types(events)

        # 異常前已送出 thinking + transcription
        assert "thinking" in types
        assert "error" in types

        err = find_event(events, "error")
        assert "message" in err["data"]

    def test_cart_update_data_structure(self, client):
        """驗證 cart_update 資料結構：items 陣列 + total"""
        dm_events = [
            {"type": "text_delta", "content": "好"},
            {
                "type": "done",
                "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 2}],
                "order_payload": {"total_price": 50},
                "finalize_result": None,
                "preview_result": None,
            },
        ]
        with patch(
            "src.api.voice_router.StreamingDMAdapter.process_input_stream",
            _dm_mock(dm_events),
        ):
            r = client.post("/api/text-chat", json={"text": "兩個薯餅", "session_id": "t-004"})

        events = parse_sse_events(r.text)
        cart = find_event(events, "cart_update")
        assert cart is not None

        data = cart["data"]
        assert "items" in data and "total" in data
        assert isinstance(data["items"], list)
        assert data["total"] == 50

        # 每個 item 必須包含 name / price / quantity
        if data["items"]:
            item = data["items"][0]
            assert all(k in item for k in ("name", "price", "quantity"))

    def test_checkout_emits_order_complete(self, client):
        """結帳流程 → order_complete 事件"""
        dm_events = [
            {
                "type": "tool_call",
                "tool_call": {"function": {"name": "finalize_order", "arguments": "{}"}},
                "tool_result": {"ok": True},
            },
            {"type": "text_delta", "content": "好，01號～"},
            {
                "type": "done",
                "cart": [],
                "order_payload": {"total_price": 50},
                "finalize_result": {
                    "ok": True,
                    "order_number": "01",
                    "order_id": "ORD-TEST",
                },
                "preview_result": None,
            },
        ]
        with patch(
            "src.api.voice_router.StreamingDMAdapter.process_input_stream",
            _dm_mock(dm_events),
        ):
            r = client.post("/api/text-chat", json={"text": "結帳", "session_id": "t-005"})

        events = parse_sse_events(r.text)
        types = event_types(events)

        assert "order_complete" in types
        oc = find_event(events, "order_complete")
        assert oc["data"]["order_number"] == "01"
        assert oc["data"]["order_id"] == "ORD-TEST"


# ── voice-chat 測試 ──


class TestVoiceChatSSE:
    """POST /api/voice-chat SSE 事件序列驗證"""

    def test_voice_event_sequence(self, client):
        """voice-chat 完整事件序列（mock orchestrator 跳過 ASR）"""
        b64_audio = base64.b64encode(FAKE_AUDIO).decode()

        async def _mock_stream(self, audio_bytes, session_id=None):
            yield {"event": "thinking", "data": {}}
            yield {"event": "transcription", "data": {"text": "我要一個飯糰"}}
            yield {"event": "status", "data": {"message": "正在加入購物車..."}}
            yield {"event": "audio_chunk", "data": b64_audio}
            yield {"event": "tts_text", "data": {"text": "好，一個飯糰～"}}
            yield {
                "event": "cart_update",
                "data": {
                    "items": [{"name": "招牌飯糰", "price": 45, "quantity": 1}],
                    "total": 45,
                },
            }

        with patch.object(StreamingOrchestrator, "process_audio_stream_v2", _mock_stream):
            r = client.post(
                "/api/voice-chat",
                data={"session_id": "v-001"},
                files={"file": ("test.webm", b"\x00" * 1000, "audio/webm")},
            )

        assert r.status_code == 200
        events = parse_sse_events(r.text)
        types = event_types(events)

        assert types[0] == "thinking"
        assert "transcription" in types
        assert "status" in types
        assert "audio_chunk" in types
        assert "cart_update" in types

        # transcription 內容驗證
        trans = find_event(events, "transcription")
        assert trans["data"]["text"] == "我要一個飯糰"

    def test_short_audio_returns_done(self, client):
        """過短音訊（< 200ms）→ 直接返回 done（跳過 ASR）"""
        r = client.post(
            "/api/voice-chat",
            data={"session_id": "v-002"},
            files={"file": ("test.webm", b"\x00" * 10, "audio/webm")},
        )

        assert r.status_code == 200
        events = parse_sse_events(r.text)

        assert len(events) == 1
        assert events[0]["event"] == "done"
        assert events[0]["data"]["cart"] == []
