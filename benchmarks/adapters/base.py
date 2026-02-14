"""
模型 Adapter 基底類別
新增模型只需繼承對應的基底類別並實作 run() 方法
"""
from abc import ABC, abstractmethod


class BaseASRAdapter(ABC):
    """ASR 模型 adapter 基底"""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def run(self, test_case: dict, timeout: float = 60) -> dict:
        """
        Args:
            test_case: {"id": str, "audio_path": str, "ground_truth": str}
        Returns:
            {"text": str, "confidence": float}
        """
        ...


class BaseTTSAdapter(ABC):
    """TTS 模型 adapter 基底"""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def run(self, test_case: dict, timeout: float = 60) -> dict:
        """
        Args:
            test_case: {"id": str, "text": str}
        Returns:
            {"audio_bytes": bytes, "first_byte_time": float, "total_time": float}
        """
        ...


class BaseLLMAdapter(ABC):
    """LLM 模型 adapter 基底"""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def run(self, test_case: dict, timeout: float = 60) -> dict:
        """
        Args:
            test_case: {"id": str, "messages": list, "expected_tools": list}
        Returns:
            {"response": str, "tool_calls": list, "tokens": int}
        """
        ...


class BaseE2EAdapter(ABC):
    """端到端模型 adapter 基底"""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def run(self, test_case: dict, timeout: float = 60) -> dict:
        """
        Args:
            test_case: {"id": str, "audio_path": str, "expected_response": str}
        Returns:
            {"response_text": str, "response_audio": bytes, "total_time": float}
        """
        ...
