# tests/services/test_voxcpm_tts.py
"""VoxCPM TTS client：length-prefix 段解析、fallback、circuit breaker、
與 _send_tts 的 streamable 逐段下發路徑"""

import time
from typing import AsyncIterator

import pytest

import src.services.streaming_orchestrator as so_module
from src.services.streaming_orchestrator import StreamingOrchestrator
from src.services.tts_implementations import VoxCPMTTSModel
from src.services.tts_interface import TTSModel


def frame(seg: bytes) -> bytes:
    """組一個 [4-byte big-endian 長度][MP3 段] frame"""
    return len(seg).to_bytes(4, "big") + seg


class FakeStreamResponse:
    def __init__(self, status_code: int, byte_chunks: list[bytes]):
        self.status_code = status_code
        self._chunks = byte_chunks

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


class FakeStreamCM:
    def __init__(self, item):
        self._item = item

    async def __aenter__(self):
        if isinstance(self._item, Exception):
            raise self._item
        return self._item

    async def __aexit__(self, *args):
        return False


class FakeClient:
    """替身 httpx.AsyncClient：依序回放 responses（元素可為 Exception）"""

    def __init__(self, responses: list):
        self.calls = 0
        self._responses = responses

    def stream(self, method, url, json=None):
        self.calls += 1
        return FakeStreamCM(self._responses.pop(0))


class FakeEdgeFallback:
    """替身 Edge fallback：yield 兩個不可獨立播放的 frame 片段"""

    cache_voice_key = "edge:fake"

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        yield b"edge-part1"
        yield b"edge-part2"


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    VoxCPMTTSModel._circuit_open_until = 0.0
    yield
    VoxCPMTTSModel._circuit_open_until = 0.0


def make_model(responses: list) -> VoxCPMTTSModel:
    model = VoxCPMTTSModel.__new__(VoxCPMTTSModel)
    model._client = FakeClient(responses)
    model._fallback = FakeEdgeFallback()
    return model


@pytest.mark.asyncio
async def test_parses_length_prefixed_segments():
    segs = [b"MP3-SEG-A", b"MP3-SEG-BB", b"MP3-SEG-CCC"]
    body = b"".join(frame(s) for s in segs)
    # 故意切在 frame 邊界之外，驗證跨 chunk 解析
    model = make_model([FakeStreamResponse(200, [body[:7], body[7:20], body[20:]])])

    out = [c async for c in model.run_stream("你好")]
    assert out == segs
    assert model.last_voice_key == "voxcpm:clone"
    assert model.stream_playable_chunks is True


@pytest.mark.asyncio
async def test_server_error_falls_back_to_single_joined_chunk():
    model = make_model([FakeStreamResponse(500, [])])

    out = [c async for c in model.run_stream("你好")]
    # Edge frame 片段必須 join 成單一 chunk（不可逐段下發）
    assert out == [b"edge-part1edge-part2"]
    assert model.last_voice_key == "edge:fake"
    assert VoxCPMTTSModel._circuit_open_until > time.monotonic()


@pytest.mark.asyncio
async def test_circuit_breaker_skips_http():
    VoxCPMTTSModel._circuit_open_until = time.monotonic() + 60
    model = make_model([])  # 不該發任何 HTTP

    out = [c async for c in model.run_stream("你好")]
    assert out == [b"edge-part1edge-part2"]
    assert model._client.calls == 0


@pytest.mark.asyncio
async def test_midstream_interruption_raises_without_fallback():
    # 第一段完整、第二段只送一半（server 中斷）
    body = frame(b"MP3-SEG-A") + (100).to_bytes(4, "big") + b"partial"
    model = make_model([FakeStreamResponse(200, [body])])

    received = []
    with pytest.raises(RuntimeError):
        async for c in model.run_stream("你好"):
            received.append(c)
    # 已下發的段保留，且不 fallback 重播整句
    assert received == [b"MP3-SEG-A"]


@pytest.mark.asyncio
async def test_connect_error_falls_back():
    model = make_model([ConnectionError("refused")])

    out = [c async for c in model.run_stream("你好")]
    assert out == [b"edge-part1edge-part2"]


# ---------- _send_tts streamable 路徑 ----------


class FakeCache:
    def __init__(self):
        self.puts = []

    def get(self, text, voice_key="default"):
        return None

    def put(self, text, audio, voice_key="default"):
        self.puts.append((text, audio, voice_key))


class StreamableTTS(TTSModel):
    stream_playable_chunks = True
    cache_voice_key = "fake:streamable"

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        self._last_voice_key = self.cache_voice_key
        yield b"seg1"
        yield b"seg2"


class BrokenStreamableTTS(StreamableTTS):
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        self._last_voice_key = self.cache_voice_key
        yield b"seg1"
        raise RuntimeError("server died")


class JoinedTTS(TTSModel):
    cache_voice_key = "fake:joined"

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        self._last_voice_key = self.cache_voice_key
        yield b"part1"
        yield b"part2"


async def collect_send_tts(tts, monkeypatch, cache):
    monkeypatch.setattr(so_module, "tts_cache", cache)
    orch = StreamingOrchestrator(None, None, tts)
    events = []
    async for evt, first_audio, ttfa in orch._send_tts("測試句", time.perf_counter(), True, "test"):
        events.append((evt, ttfa))
    return events


@pytest.mark.asyncio
async def test_send_tts_streamable_emits_per_segment(monkeypatch):
    cache = FakeCache()
    events = await collect_send_tts(StreamableTTS(), monkeypatch, cache)

    assert len(events) == 2  # 每段一個 audio_chunk 事件
    assert events[0][1] is not None  # TTFA 只在首段
    assert events[1][1] is None
    # cache 存 join 後的完整音訊
    assert cache.puts == [("測試句", b"seg1seg2", "fake:streamable")]


@pytest.mark.asyncio
async def test_send_tts_streamable_interruption_skips_cache(monkeypatch):
    cache = FakeCache()
    events = await collect_send_tts(BrokenStreamableTTS(), monkeypatch, cache)

    assert len(events) == 1  # 已下發的首段保留
    assert cache.puts == []  # 半句不入快取


@pytest.mark.asyncio
async def test_send_tts_joined_single_event(monkeypatch):
    cache = FakeCache()
    events = await collect_send_tts(JoinedTTS(), monkeypatch, cache)

    assert len(events) == 1
    assert events[0][1] is not None
    assert cache.puts == [("測試句", b"part1part2", "fake:joined")]
