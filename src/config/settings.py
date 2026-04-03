# src/config/settings.py
"""統一環境變量管理 — Pydantic Settings"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.dev"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 環境分層 ---
    ENVIRONMENT: str = "dev"  # "dev" | "prod"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    REDIS_URL: str = ""  # 空字串 = InMemory fallback
    SESSION_TTL_MINUTES: int = 30

    # --- 模型配置 ---
    ASR_BACKEND: str = "sensevoice"  # "sensevoice" | "qwen3asr"
    TTS_BACKEND: str = "edgetts"  # "edgetts" | "qwen3tts" | "omnivoice"
    QWEN3ASR_MODEL_SIZE: str = "0.6b"  # "0.6b" | "1.7b"
    SENSEVOICE_MODEL: str = "iic/SenseVoiceSmall"
    SENSEVOICE_HUB: str = "ms"  # "ms" = ModelScope
    QWEN3TTS_MODEL: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    QWEN3TTS_SPEAKER: str = "Vivian"
    OMNIVOICE_BASE_URL: str = "http://127.0.0.1:8100"

    # --- LLM 服務 ---
    LLM_BASE_URL: str = "http://127.0.0.1:1234/v1/chat/completions"
    LLM_MODEL: str = "qwen/qwen3-30b-a3b-2507"
    LLM_TIMEOUT: int = 120

    # --- 店家設定 ---
    STORE_NAME: str = "源飯糰"

    # --- 認證 ---
    API_KEY: str | None = None

    # --- 日誌與效能 ---
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "color"  # "color" | "json"
    LOG_RETENTION_DAYS: int = 7  # dev 7 天、prod 建議 30 天
    PERF_SLOW_THRESHOLD: float = 5.0

    # --- 上傳限制 ---
    MAX_AUDIO_SIZE_BYTES: int = 10 * 1024 * 1024  # 10MB

    # --- API 限流 ---
    RATE_LIMIT_DIALOGUE: str = "10/minute"
    RATE_LIMIT_CHECKOUT: str = "5/minute"
    RATE_LIMIT_QUERY: str = "60/minute"
    RATE_LIMIT_TEST: str = "30/minute"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "prod"


settings = Settings()
