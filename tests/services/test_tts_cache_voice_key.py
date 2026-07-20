# tests/services/test_tts_cache_voice_key.py
"""TTS cache voice_key 維度測試 + warmup gate 測試"""

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.tts_cache import TTSCache, wait_for_tts_health
from src.services.tts_interface import TTSModel


# ---------------------------------------------------------------------------
# 輔助 mock
# ---------------------------------------------------------------------------


_EDGE_KEY = "edge:zh-TW-HsiaoChenNeural"


class _FakeTTS(TTSModel):
    """最小 TTS stub，固定回傳 b'audio'，voice_key 可指定"""

    def __init__(self, voice_key: str = "fake:v1"):
        self._key = voice_key

    @property
    def cache_voice_key(self) -> str:
        return self._key

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        self._last_voice_key = self.cache_voice_key
        yield b"audio"


class _FallbackTTS(_FakeTTS):
    """模擬 OmniVoice fallback 到 Edge：last_voice_key 回報 Edge 聲音"""

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        self._last_voice_key = _EDGE_KEY
        yield b"edge_audio"


# ---------------------------------------------------------------------------
# 1. voice_key 維度測試
# ---------------------------------------------------------------------------


def test_different_voice_keys_are_separate_cache_entries():
    """相同文字、不同 voice_key → 不同 cache entry，不互相命中"""
    cache = TTSCache()
    text = "好的"
    cache.put(text, b"audio_clone", voice_key="omnivoice:clone")
    cache.put(text, b"audio_edge", voice_key="edge:zh-TW-HsiaoChenNeural")

    assert cache.get(text, voice_key="omnivoice:clone") == b"audio_clone"
    assert cache.get(text, voice_key="edge:zh-TW-HsiaoChenNeural") == b"audio_edge"
    # 不同 key 不互相命中
    assert cache.get(text, voice_key="omnivoice:instruct") is None


def test_same_voice_key_normalized_text_hits():
    """帶標點的文字正規化後與無標點版共用 cache entry"""
    cache = TTSCache()
    cache.put("好的", b"audio", voice_key="omnivoice:clone")
    # 正規化後相同（好的 → 好的，無標點），這裡測帶標點文字是否能透過正規化命中
    cache.put("好的！", b"audio_punct", voice_key="omnivoice:clone")
    # "好的！" 正規化 → "好的"，應該覆蓋前一筆（runtime cache 同 key）
    assert cache.get("好的", voice_key="omnivoice:clone") == b"audio_punct"


def test_warmup_uses_voice_key():
    """warmup 存入 warmup_cache 時使用 voice_key 作為 key 前綴"""
    cache = TTSCache()
    cache._store_warmup("好", b"audio", voice_key="omnivoice:clone")
    assert cache.get("好", voice_key="omnivoice:clone") == b"audio"
    assert cache.get("好", voice_key="omnivoice:instruct") is None
    assert cache.get("好", voice_key="default") is None


# ---------------------------------------------------------------------------
# 2. fallback 隔離測試（fallback 產物存 fallback 聲音的 key，不污染本尊）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_stores_fallback_under_fallback_key():
    """warmup 中 run_stream 走 fallback 時，音訊存到 Edge key，不污染 OmniVoice key"""
    cache = TTSCache()
    tts = _FallbackTTS(voice_key="omnivoice:clone")

    await cache.warmup(tts)

    # OmniVoice key 下不應有任何 fallback 產物
    assert cache.get("好", voice_key="omnivoice:clone") is None
    # fallback 產物存在 Edge key 下（backend 切到 edge 時可直接命中）
    assert cache.get("好", voice_key=_EDGE_KEY) == b"edge_audio"


@pytest.mark.asyncio
async def test_warmup_stores_normal_audio_under_own_key():
    """warmup 正常路徑的音訊存到本尊 voice key"""
    cache = TTSCache()
    tts = _FakeTTS(voice_key="omnivoice:clone")

    await cache.warmup(tts)

    assert cache.get("好", voice_key="omnivoice:clone") == b"audio"
    assert cache.get("好", voice_key="omnivoice:instruct") is None


def test_orchestrator_caches_fallback_under_fallback_key(monkeypatch):
    """orchestrator _send_tts：fallback 時 put 以 fallback 聲音的 key 存入"""
    from src.services import streaming_orchestrator as orch_mod

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # 強制 cache miss

    monkeypatch.setattr(orch_mod, "tts_cache", mock_cache)

    fallback_tts = _FallbackTTS(voice_key="omnivoice:clone")

    from src.services.streaming_orchestrator import StreamingOrchestrator

    orchestrator = StreamingOrchestrator(
        asr_service=None,
        dialogue_manager=None,
        tts_service=fallback_tts,
    )

    async def _run():
        async for _ in orchestrator._send_tts("好的", request_start=0.0, first_audio=True):
            pass

    asyncio.run(_run())

    mock_cache.put.assert_called_once()
    assert mock_cache.put.call_args.kwargs.get("voice_key") == _EDGE_KEY


def test_orchestrator_caches_normal_run(monkeypatch):
    """orchestrator _send_tts：正常路徑以本尊 voice key 存入"""
    from src.services import streaming_orchestrator as orch_mod

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # 強制 cache miss

    monkeypatch.setattr(orch_mod, "tts_cache", mock_cache)

    normal_tts = _FakeTTS(voice_key="omnivoice:clone")

    from src.services.streaming_orchestrator import StreamingOrchestrator

    orchestrator = StreamingOrchestrator(
        asr_service=None,
        dialogue_manager=None,
        tts_service=normal_tts,
    )

    async def _run():
        async for _ in orchestrator._send_tts("好的", request_start=0.0, first_audio=True):
            pass

    asyncio.run(_run())

    mock_cache.put.assert_called_once()
    assert mock_cache.put.call_args.kwargs.get("voice_key") == "omnivoice:clone"


# ---------------------------------------------------------------------------
# 3. warmup gate 測試
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_tts_health_returns_true_on_200():
    """health 回傳 200 → wait_for_tts_health 回傳 True"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.tts_cache.httpx.AsyncClient", return_value=mock_client):
        result = await wait_for_tts_health(
            "http://127.0.0.1:8100/health", max_wait=4, interval=2.0
        )

    assert result is True


@pytest.mark.asyncio
async def test_wait_for_tts_health_returns_false_on_timeout():
    """health 持續失敗（連線錯誤）→ 超時後回傳 False，不預熱"""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.tts_cache.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.tts_cache.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_tts_health(
                "http://127.0.0.1:8100/health", max_wait=4, interval=2.0
            )

    assert result is False


@pytest.mark.asyncio
async def test_wait_for_tts_health_returns_false_on_non_200():
    """health 回傳 503（模型尚未載入）→ 超時後回傳 False"""
    mock_resp = MagicMock()
    mock_resp.status_code = 503

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.tts_cache.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.tts_cache.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_tts_health(
                "http://127.0.0.1:8100/health", max_wait=4, interval=2.0
            )

    assert result is False
