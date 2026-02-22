# src/config/models.py
"""模型配置 — 修改此檔案切換後端"""
import os

# 後端選擇（可用環境變數覆蓋）
ASR_BACKEND = os.getenv("ASR_BACKEND", "sensevoice")  # "qwen3asr" | "sensevoice"
TTS_BACKEND = os.getenv("TTS_BACKEND", "edgetts")      # "edgetts" | "qwen3tts"

# SenseVoice 設定（必須用 modelscope hub，HuggingFace 版權重解碼異常）
SENSEVOICE_MODEL = os.getenv("SENSEVOICE_MODEL", "iic/SenseVoiceSmall")
SENSEVOICE_HUB = os.getenv("SENSEVOICE_HUB", "ms")  # "ms" = ModelScope

# Qwen3-TTS 設定
QWEN3TTS_MODEL = os.getenv("QWEN3TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
QWEN3TTS_SPEAKER = os.getenv("QWEN3TTS_SPEAKER", "Vivian")  # 預設女聲

# LLM：在 LM Studio 手動載入以下模型（不影響程式碼，僅文件用）
# 推薦：qwen3-30b-a3b (MoE, 3B 活躍參數) — 適合 RTX 5070 Ti 16GB
LLM_RECOMMENDED = "qwen/qwen3-30b-a3b-2507"
