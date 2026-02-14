"""
TTS 模型 Adapters
新增 TTS 模型：1) 建立子類別 2) 在 REGISTRY 註冊
"""
import asyncio
import sys
import time
from pathlib import Path

from benchmarks.adapters.base import BaseTTSAdapter

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class EdgeTTSAdapter(BaseTTSAdapter):
    """Edge TTS adapter（使用現有 EdgeTTSModel）"""

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        from src.services.tts_implementations import EdgeTTSModel
        tts = EdgeTTSModel(voice=self.params.get("voice", "zh-TW-HsiaoChenNeural"))

        chunks = []
        first_byte_time = None
        start = time.perf_counter()

        async def _collect():
            nonlocal first_byte_time
            async for chunk in tts.run_stream(test_case["text"]):
                if first_byte_time is None:
                    first_byte_time = time.perf_counter() - start
                chunks.append(chunk)

        asyncio.run(_collect())
        total_time = time.perf_counter() - start

        return {
            "audio_bytes": b"".join(chunks),
            "first_byte_time": first_byte_time or total_time,
            "total_time": total_time,
        }


class CosyVoice2Adapter(BaseTTSAdapter):
    """CosyVoice 2 adapter（待實作）"""

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        raise NotImplementedError("CosyVoice 2 adapter 尚未實作")


class ElevenLabsAdapter(BaseTTSAdapter):
    """ElevenLabs API adapter（待實作）"""

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        import os
        api_key = os.getenv(self.params.get("api_key_env", "ELEVENLABS_API_KEY"))
        if not api_key:
            raise ValueError("需設定 ELEVENLABS_API_KEY 環境變數")
        raise NotImplementedError("ElevenLabs adapter 尚未實作")


REGISTRY = {
    "edge_tts": EdgeTTSAdapter,
    "cosyvoice2": CosyVoice2Adapter,
    "elevenlabs": ElevenLabsAdapter,
}


def create_tts_adapter(adapter_name: str, params: dict) -> BaseTTSAdapter:
    cls = REGISTRY.get(adapter_name)
    if cls is None:
        raise ValueError(f"未知的 TTS adapter: {adapter_name}，可用: {list(REGISTRY.keys())}")
    return cls(params)
