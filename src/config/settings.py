# src/config/settings.py
"""統一環境變量管理 — Pydantic Settings"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 模型配置 ---
    ASR_BACKEND: str = "sensevoice"       # "sensevoice" | "qwen3asr"
    TTS_BACKEND: str = "edgetts"          # "edgetts" | "qwen3tts"
    SENSEVOICE_MODEL: str = "iic/SenseVoiceSmall"
    SENSEVOICE_HUB: str = "ms"            # "ms" = ModelScope
    QWEN3TTS_MODEL: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    QWEN3TTS_SPEAKER: str = "Vivian"

    # --- LLM 服務 ---
    LLM_BASE_URL: str = "http://127.0.0.1:1234/v1/chat/completions"
    LLM_MODEL: str = "qwen/qwen3-30b-a3b-2507"
    LLM_TIMEOUT: int = 120

    # --- 認證 ---
    API_KEY: str | None = None

    # --- 日誌與效能 ---
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "color"             # "color" | "json"
    PERF_SLOW_THRESHOLD: float = 5.0

    # --- Session ---
    SESSION_TTL_MINUTES: int = 30


settings = Settings()
