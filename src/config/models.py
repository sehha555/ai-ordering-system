# src/config/models.py
"""模型配置 — 修改此檔案切換後端"""
import os

# 後端選擇（可用環境變數覆蓋）
ASR_BACKEND = os.getenv("ASR_BACKEND", "sensevoice")  # "qwen3asr" | "sensevoice"
TTS_BACKEND = os.getenv("TTS_BACKEND", "qwen3tts")    # "edgetts" | "qwen3tts"

# SenseVoice 設定
SENSEVOICE_MODEL = os.getenv("SENSEVOICE_MODEL", "FunAudioLLM/SenseVoiceSmall")
SENSEVOICE_HUB = os.getenv("SENSEVOICE_HUB", "hf")  # "hf" = HuggingFace

# Qwen3-TTS 設定
QWEN3TTS_MODEL = os.getenv("QWEN3TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
QWEN3TTS_SPEAKER = os.getenv("QWEN3TTS_SPEAKER", "Vivian")  # 預設女聲

# LLM：在 LM Studio 手動載入以下模型（不影響程式碼，僅文件用）
# 推薦：qwen3-14b (Q4_K_M, ~9GB VRAM) — 適合 RTX 5070 Ti 16GB
LLM_RECOMMENDED = "qwen3-14b"
