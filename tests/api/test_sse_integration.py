"""SSE 整合測試 — 驗證 /api/text-chat 和 /api/voice-chat 的事件序列

Mock 策略：
- DM 層（StreamingDMAdapter.process_input_stream）→ yield 預定義事件
- TTS 快取 → 所有文字命中，返回假 MP3 bytes
- voice-chat 額外 mock StreamingOrchestrator.process_audio_stream_v2（跳過 ASR/ffmpeg）
"""

import json
import base64
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.services.streaming_orchestrator import StreamingOrchestrator, _TOOL_STATUS_MAP

# ── helpers ──

FAKE_AUDIO = b"\xff\xfb\x90\x00" * 10  # 假 MP3 bytes
_DM_PATCH_TARGET = "src.api.voice_router.StreamingDMAdapter.process_input_stream"


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
    # flush：若 stream 未以空行結尾，補收最後一個事件
    if current_event is not None:
        events.append({"event": current_event, "data": current_data})
    return events


def event_types(events: list[dict]) -> list[str]:
    return [e["event"] for e in events]


def find_event(events: list[dict], name: str) -> dict | None:
    return next((e for e in events if e["event"] == name), None)


def _dm_mock(events: list[dict]):
    """建立 DM process_input_stream mock"""

    async def _gen(self, text):
        for evt in events:
            yield evt

    return _gen


# ── fixtures ──


def _make_client():
    from src.api.app import app

    return TestClient(app)


# ── text-chat 測試 ──


class TestTextChatSSE:
    """POST /api/text-chat SSE 事件序列驗證"""

    def setup_method(self):
        self.client = _make_client()
        self._tts_patcher = patch("src.services.streaming_orchestrator.tts_cache")
        mc = self._tts_patcher.start()
        mc.get.return_value = FAKE_AUDIO

    def teardown_method(self):
        self._tts_patcher.stop()

    def test_simple_reply_event_sequence(self):
        """簡單回覆：thinking → transcription → audio_chunk → tts_text → cart_update"""
        dm_events = [
            {"type": "text_delta", "content": "好的，還需要什麼嗎？"},
            {
                "type": "done",
                "cart": [],
                "finalize_result": None,
                "preview_result": None,
            },
        ]
        with patch(_DM_PATCH_TARGET, _dm_mock(dm_events)):
            r = self.client.post("/api/text-chat", json={"text": "你好", "session_id": "t-001"})

        assert r.status_code == 200
        events = parse_sse_events(r.text)
        types = event_types(events)

        assert types[0] == "thinking"
        assert types[1] == "transcription"
        assert "audio_chunk" in types
        assert "tts_text" in types
        assert types[-1] == "cart_update"

        trans = find_event(events, "transcription")
        assert trans["data"]["text"] == "你好"

    def test_tool_call_adds_status_event(self):
        """tool call → 多出 status 事件 + early_tts 產生 audio_chunk"""
        dm_events = [
            {
                "type": "tool_call",
                "tool_call": {"function": {"name": "add_item", "arguments": "{}"}},
                "tool_result": {"ok": True},
            },
            {"type": "early_tts", "content": "好，一個薯餅～還要什麼？"},
            {
                "type": "done",
                "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
                "finalize_result": None,
                "preview_result": None,
            },
        ]
        with patch(_DM_PATCH_TARGET, _dm_mock(dm_events)):
            r = self.client.post(
                "/api/text-chat", json={"text": "我要一個薯餅", "session_id": "t-002"}
            )

        events = parse_sse_events(r.text)
        types = event_types(events)

        assert "status" in types
        status = find_event(events, "status")
        assert status["data"]["message"] == _TOOL_STATUS_MAP["add_item"]

        assert "audio_chunk" in types

        # total 由 orchestrator 從 cart 實際計價（薯餅(1片) = $20）
        cart = find_event(events, "cart_update")
        assert cart["data"]["total"] == 20
        assert len(cart["data"]["items"]) == 1

    def test_error_yields_sse_error_event(self):
        """DM 層拋異常 → _sse_wrap 捕捉 → SSE error 事件"""

        async def _boom(self, text):
            raise RuntimeError("LLM 連線逾時")
            yield  # unreachable — 使 Python 將此函式視為 async generator

        with patch(_DM_PATCH_TARGET, _boom):
            r = self.client.post("/api/text-chat", json={"text": "你好", "session_id": "t-003"})

        assert r.status_code == 200
        events = parse_sse_events(r.text)
        types = event_types(events)

        assert "thinking" in types
        assert "error" in types

        err = find_event(events, "error")
        assert "message" in err["data"]

    def test_cart_update_data_structure(self):
        """驗證 cart_update 資料結構：items 陣列 + total"""
        dm_events = [
            {"type": "text_delta", "content": "好"},
            {
                "type": "done",
                "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 2}],
                "finalize_result": None,
                "preview_result": None,
            },
        ]
        with patch(_DM_PATCH_TARGET, _dm_mock(dm_events)):
            r = self.client.post("/api/text-chat", json={"text": "兩個薯餅", "session_id": "t-004"})

        events = parse_sse_events(r.text)
        cart = find_event(events, "cart_update")
        assert cart is not None

        data = cart["data"]
        assert "items" in data and "total" in data
        assert isinstance(data["items"], list)
        # total 由 orchestrator 從 cart 實際計價（薯餅(1片) x2 = $40）
        assert data["total"] == 40

        if data["items"]:
            item = data["items"][0]
            assert all(k in item for k in ("name", "price", "quantity"))

    def test_checkout_emits_order_complete(self):
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
                "finalize_result": {
                    "ok": True,
                    "order_number": "01",
                    "order_id": "ORD-TEST",
                },
                "preview_result": None,
            },
        ]
        with patch(_DM_PATCH_TARGET, _dm_mock(dm_events)):
            r = self.client.post("/api/text-chat", json={"text": "結帳", "session_id": "t-005"})

        events = parse_sse_events(r.text)
        types = event_types(events)

        assert "order_complete" in types
        oc = find_event(events, "order_complete")
        assert oc["data"]["order_number"] == "01"
        assert oc["data"]["order_id"] == "ORD-TEST"


# ── voice-chat 測試 ──


class TestVoiceChatSSE:
    """POST /api/voice-chat SSE 事件序列驗證"""

    def setup_method(self):
        self.client = _make_client()
        self._tts_patcher = patch("src.services.streaming_orchestrator.tts_cache")
        mc = self._tts_patcher.start()
        mc.get.return_value = FAKE_AUDIO

    def teardown_method(self):
        self._tts_patcher.stop()

    def test_voice_event_sequence(self):
        """voice-chat 完整事件序列（mock orchestrator 跳過 ASR）"""
        b64_audio = base64.b64encode(FAKE_AUDIO).decode()

        async def _mock_stream(self, audio_bytes, session_id=None, audio_path=None):
            yield {"event": "thinking", "data": {}}
            yield {"event": "transcription", "data": {"text": "我要一個飯糰"}}
            yield {"event": "status", "data": {"message": _TOOL_STATUS_MAP["add_item"]}}
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
            r = self.client.post(
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

        trans = find_event(events, "transcription")
        assert trans["data"]["text"] == "我要一個飯糰"

    def test_short_audio_returns_done(self):
        """過短音訊（< 200ms）→ 直接返回 done（跳過 ASR）"""
        r = self.client.post(
            "/api/voice-chat",
            data={"session_id": "v-002"},
            files={"file": ("test.webm", b"\x00" * 10, "audio/webm")},
        )

        assert r.status_code == 200
        events = parse_sse_events(r.text)

        assert len(events) == 1
        assert events[0]["event"] == "done"
        assert events[0]["data"]["cart"] == []


# ── SET_QTY tag strip 回歸測試 ──


class TestSetQtyTagStrip:
    """回歸測試：streaming text_delta 中 [SET_QTY:...] tag 應被 strip"""

    def setup_method(self):
        self.client = _make_client()
        self._tts_patcher = patch("src.services.streaming_orchestrator.tts_cache")
        mc = self._tts_patcher.start()
        mc.get.return_value = FAKE_AUDIO

    def teardown_method(self):
        self._tts_patcher.stop()

    def test_set_qty_tag_not_leaked_to_text_delta(self):
        """LLM 輸出含 [SET_QTY:薯餅|qty=1] 時，SSE text_delta 不含 tag、後續文字保留"""
        from unittest.mock import MagicMock
        from src.services import container as _container

        # 建立假 LLM caller：只回傳含 SET_QTY tag 的 text_delta + done
        async def _fake_run_turn_stream(*args, **kwargs):
            yield {"type": "text_delta", "content": "[SET_QTY:薯餅|qty=1]好，薯餅改成一個～"}
            yield {
                "type": "done",
                "assistant_text": "[SET_QTY:薯餅|qty=1]好，薯餅改成一個～",
                "history": [],
                "usage": {},
                "tool_trace": [],
            }

        mock_llm = MagicMock()
        mock_llm.run_turn_stream.side_effect = _fake_run_turn_stream

        original_llm = _container.llm_caller
        _container.llm_caller = mock_llm
        try:
            r = self.client.post(
                "/api/text-chat",
                json={"text": "薯餅改成一個", "session_id": "test-set-qty-strip-001"},
            )
        finally:
            _container.llm_caller = original_llm

        assert r.status_code == 200
        events = parse_sse_events(r.text)

        # 找出所有 text_delta SSE 事件
        text_delta_events = [e for e in events if e["event"] == "text_delta"]
        assert text_delta_events, "應至少有一個 text_delta SSE 事件"

        combined = "".join(e["data"]["text"] for e in text_delta_events)
        assert "[SET_QTY:" not in combined, (
            f"[SET_QTY:...] tag 不應出現在 text_delta 輸出中，實際: {combined!r}"
        )
        assert "好，薯餅改成一個" in combined, f"tag 後的文字應保留，實際: {combined!r}"


# ── [CHECKOUT] 輪話術 surface 測試 ──


class TestCheckoutTurnSurface:
    """[CHECKOUT] 輪 LLM 原話 hold，execute_tags 最終話術（確認句）送到 SSE/TTS"""

    def setup_method(self):
        self.client = _make_client()
        self._tts_patcher = patch("src.services.streaming_orchestrator.tts_cache")
        mc = self._tts_patcher.start()
        mc.get.return_value = FAKE_AUDIO

    def teardown_method(self):
        self._tts_patcher.stop()

    def _post_with_fake_llm(self, llm_text: str, user_text: str, session_id: str):
        from unittest.mock import MagicMock
        from src.services import container as _container

        async def _fake_run_turn_stream(*args, **kwargs):
            yield {"type": "text_delta", "content": llm_text}
            yield {
                "type": "done",
                "assistant_text": llm_text,
                "history": [],
                "usage": {},
                "tool_trace": [],
            }

        mock_llm = MagicMock()
        mock_llm.run_turn_stream.side_effect = _fake_run_turn_stream

        original_llm = _container.llm_caller
        _container.llm_caller = mock_llm
        try:
            return self.client.post(
                "/api/text-chat", json={"text": user_text, "session_id": session_id}
            )
        finally:
            _container.llm_caller = original_llm

    def test_checkout_first_question_replaced_by_confirm(self):
        """進結帳沒帶內用外帶 → SSE 是後端確認句（品項+金額），非 LLM 原話"""
        from src.services import container as _container

        session_id = "test-ck-surface-001"
        session = _container.session_store.get(session_id)
        session["cart"] = [
            {"itemtype": "riceball", "flavor": "源味傳統", "rice": "紫米", "quantity": 1}
        ]
        session["llm_history"] = []
        _container.session_store.set(session_id, session)

        r = self._post_with_fake_llm("[CHECKOUT]好的～內用還是外帶？", "結帳", session_id)

        assert r.status_code == 200
        events = parse_sse_events(r.text)
        combined = "".join(e["data"]["text"] for e in events if e["event"] == "text_delta")

        assert "跟您確認" in combined, f"應送出後端確認句，實際: {combined!r}"
        assert "內用還是外帶" in combined
        assert "好的～內用還是外帶" not in combined, "LLM 原話應被 hold 不送出"

        tts = find_event(events, "tts_text")
        assert tts and "跟您確認" in tts["data"]["text"]

    def test_checkout_same_sentence_finalize_reply_surfaced(self):
        """同句帶外帶+現金 → SSE 是 finalize 報號帶金額，非 LLM 原話"""
        from src.services import container as _container

        session_id = "test-ck-surface-002"
        session = _container.session_store.get(session_id)
        session["cart"] = [
            {"itemtype": "riceball", "flavor": "源味傳統", "rice": "紫米", "quantity": 1}
        ]
        session["llm_history"] = []
        _container.session_store.set(session_id, session)

        r = self._post_with_fake_llm("[CHECKOUT]好～外帶付現金喔！", "結帳 外帶 現金", session_id)

        assert r.status_code == 200
        events = parse_sse_events(r.text)
        combined = "".join(e["data"]["text"] for e in events if e["event"] == "text_delta")

        assert "號" in combined and "元" in combined, f"應報單號+金額，實際: {combined!r}"
        assert find_event(events, "order_complete") is not None
