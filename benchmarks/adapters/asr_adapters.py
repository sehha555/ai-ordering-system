"""
ASR 模型 Adapters
新增 ASR 模型：1) 建立子類別 2) 在 REGISTRY 註冊
"""
import sys
from pathlib import Path

from benchmarks.adapters.base import BaseASRAdapter
from src.services.asr_postprocess import postprocess

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class Qwen3ASRAdapter(BaseASRAdapter):
    """Qwen3-ASR adapter（使用現有 ASRService）"""

    def __init__(self, params: dict):
        super().__init__(params)
        self._service = None

    def _init_service(self):
        if self._service is None:
            from src.services.asr_service import ASRService
            self._service = ASRService(
                model_size=self.params.get("model_size", "turbo"),
                language=self.params.get("language", "zh"),
            )

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._init_service()
        result = self._service.transcribe(test_case["audio_path"])
        return {
            "text": postprocess(result.get("text", "")),
            "confidence": result.get("confidence", 0.0),
        }


class SenseVoiceAdapter(BaseASRAdapter):
    """SenseVoice adapter（使用現有 SenseVoiceService）"""

    def __init__(self, params: dict):
        super().__init__(params)
        self._service = None

    def _init_service(self):
        if self._service is None:
            from src.services.asr_service import SenseVoiceService
            from src.config.models import SENSEVOICE_MODEL, SENSEVOICE_HUB
            self._service = SenseVoiceService(
                model_id=SENSEVOICE_MODEL,
                language=self.params.get("language", "zh"),
                hub=SENSEVOICE_HUB,
            )

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._init_service()
        result = self._service.transcribe(test_case["audio_path"])
        return {
            "text": postprocess(result.get("text", "")),
            "confidence": result.get("confidence", 0.0),
        }


REGISTRY = {
    "qwen3": Qwen3ASRAdapter,
    "sensevoice": SenseVoiceAdapter,
}


def create_asr_adapter(adapter_name: str, params: dict) -> BaseASRAdapter:
    cls = REGISTRY.get(adapter_name)
    if cls is None:
        raise ValueError(f"未知的 ASR adapter: {adapter_name}，可用: {list(REGISTRY.keys())}")
    return cls(params)
