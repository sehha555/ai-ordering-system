# src/config/models.py
"""模型配置 — 修改此檔案切換後端"""

from src.config.settings import settings

# 後端選擇（統一從 Settings 讀取）
ASR_BACKEND = settings.ASR_BACKEND
TTS_BACKEND = settings.TTS_BACKEND

# SenseVoice 設定（必須用 modelscope hub，HuggingFace 版權重解碼異常）
SENSEVOICE_MODEL = settings.SENSEVOICE_MODEL
SENSEVOICE_HUB = settings.SENSEVOICE_HUB

# Qwen3-ASR 設定
QWEN3ASR_MODEL_SIZE = settings.QWEN3ASR_MODEL_SIZE

# Qwen3-TTS 設定
QWEN3TTS_MODEL = settings.QWEN3TTS_MODEL
QWEN3TTS_SPEAKER = settings.QWEN3TTS_SPEAKER

# OmniVoice / VoxCPM 設定（微服務架構，只需 base_url）
OMNIVOICE_BASE_URL = settings.OMNIVOICE_BASE_URL
VOXCPM_BASE_URL = settings.VOXCPM_BASE_URL

# 微服務型 TTS backend 的 health URL 單一對照表 —
# warmup gate（app.py）與 readyz（health.py）都查這裡，新增 backend 只需加一筆
TTS_SERVICE_HEALTH_URLS = {
    "omnivoice": OMNIVOICE_BASE_URL.rstrip("/") + "/health",
    "voxcpm": VOXCPM_BASE_URL.rstrip("/") + "/health",
}

# LLM：在 LM Studio 手動載入以下模型（不影響程式碼，僅文件用）
# 推薦：qwen3-30b-a3b (MoE, 3B 活躍參數) — 適合 RTX 5070 Ti 16GB
LLM_RECOMMENDED = "qwen/qwen3-30b-a3b-2507"
