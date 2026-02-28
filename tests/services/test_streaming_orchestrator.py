# tests/services/test_streaming_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.streaming_orchestrator import StreamingOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_flow():
    # Mock dependencies
    mock_asr = AsyncMock()
    mock_asr.transcribe.return_value = "我要一個飯糰"

    # process_input_stream 是 async generator，yield done event
    async def mock_input_stream(text):
        yield {"type": "text_delta", "content": "好的，"}
        yield {"type": "text_delta", "content": "一個飯糰。"}
        yield {
            "type": "done",
            "assistant_text": "好的，一個飯糰。",
            "history": [],
            "tool_trace": [],
            "cart": [],
            "order_payload": {"total_price": 0},
            "finalize_result": None,
        }

    mock_dm = MagicMock()
    mock_dm.process_input_stream = mock_input_stream

    mock_tts = AsyncMock()

    async def async_gen(text):
        yield b"audio_data"

    mock_tts.run_stream = async_gen

    orchestrator = StreamingOrchestrator(mock_asr, mock_dm, mock_tts)

    events = []
    async for event in orchestrator.process_audio_stream_v2(b"fake_audio_blob"):
        events.append(event)

    # Verify sequence of events
    event_types = [e["event"] for e in events]
    assert "transcription" in event_types
    assert "thinking" in event_types
    assert "cart_update" in event_types
    assert "audio_chunk" in event_types
