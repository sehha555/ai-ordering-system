# ASR/TTS 語音集成指南

## 概述

本指南說明如何使用 **Whisper (ASR)** 和 **pyttsx3 (TTS)** 為您的訂餐系統添加語音功能。

### 已實現的功能

✅ **ASR (自動語音識別)**
- 使用 OpenAI Whisper
- 支持中文語音識別
- 支持文件和字節流輸入
- 自動語言檢測

✅ **TTS (文本轉語音)**
- 使用 pyttsx3
- 支持實時播放和文件保存
- 可調節語速和音量
- 支持異步操作

✅ **API 端點**
- `/dialogue/text` - 文本對話
- `/dialogue/voice` - 語音對話
- `/asr/test` - ASR 狀態檢查
- `/tts/test` - TTS 狀態檢查

---

## 安裝

### 依賴包

```bash
# ASR (語音識別)
pip install openai-whisper

# TTS (文字轉語音)
pip install pyttsx3

# 輔助庫
pip install soundfile librosa numpy
```

### 快速驗證

```bash
# 檢查 Whisper 是否正確安裝
python -c "import whisper; print('Whisper OK')"

# 檢查 pyttsx3 是否正確安裝
python -c "import pyttsx3; print('pyttsx3 OK')"
```

---

## 文件結構

```
src/services/
├── asr_service.py       # ASR 服務實現
├── tts_service.py       # TTS 服務實現
└── llm_tool_caller.py   # LLM 調用（已有）

src/api/
└── app.py              # FastAPI 應用（已更新）

tests/
└── test_asr_tts_integration.py  # 集成測試
```

---

## 使用方法

### 1️⃣ ASR Service（語音識別）

#### 初始化

```python
from src.services.asr_service import ASRService

# 初始化（第一次運行會下載 base 模型 ~140MB）
asr = ASRService(model_size="base", language="zh")
```

#### 轉錄文件

```python
# 支持格式: mp3, wav, m4a, flac, ogg 等
result = asr.transcribe("audio.wav")

# 結果格式:
{
    "text": "我要飯糰",                    # 識別出的文字
    "language": "zh",                  # 檢測到的語言
    "confidence": 0.95,                # 信心度
    "segments": [...]                  # 分段信息
}
```

#### 轉錄字節流

```python
import numpy as np

# 將原始音訊字節轉換為文字
# sample_rate: 採樣率 (Hz)，通常 16000 或 44100
result = asr.transcribe_bytes(audio_bytes, sample_rate=16000)
```

---

### 2️⃣ TTS Service（文字轉語音）

#### 初始化

```python
from src.services.tts_service import TTSService

# 初始化
tts = TTSService(language="zh", rate=150, volume=1.0)

# 參數說明：
# - language: "zh" (中文) 或 "en" (英文)
# - rate: 語速 50-300 (越高越快)
# - volume: 音量 0.0-1.0
```

#### 播放語音

```python
# 直接播放（同步）
result = tts.speak("歡迎光臨，請問要點什麼？")
# 結果: {"status": "success", "text": "...", "file_path": None}

# 播放並保存到文件（同步）
result = tts.speak("歡迎光臨", save_to_file="greeting.wav")
# 結果: {"status": "success", "text": "...", "file_path": "greeting.wav"}

# 異步播放（不等待完成）
result = tts.speak_async("歡迎光臨")
# 結果: {"status": "queued", "text": "..."}
```

#### 調整語速和音量

```python
# 調整語速
tts.set_rate(200)  # 更快

# 調整音量
tts.set_volume(0.8)  # 稍微降低音量
```

#### 查看可用語音

```python
properties = tts.get_properties()
print(properties["voices"])
# 結果:
# [
#   {"id": "...", "name": "...", "languages": [...]},
#   ...
# ]
```

---

## API 使用

### 文本對話

```bash
curl -X POST http://localhost:8000/dialogue/text \
  -H "X-API-Key: yuan-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "user123",
    "text": "我要飯糰"
  }'

# 響應:
{
  "session_id": "user123",
  "response": "想要哪個口味的飯糰？",
  "status": "ok"
}
```

### 語音對話

```bash
# 上傳語音文件進行對話
curl -X POST http://localhost:8000/dialogue/voice \
  -H "X-API-Key: yuan-secret-key" \
  -F "session_id=user123" \
  -F "audio_file=@speech.wav"

# 響應:
{
  "session_id": "user123",
  "status": "ok",
  "user_text": "我要飯糰",
  "response": "想要哪個口味的飯糰？",
  "audio_url": null
}
```

### 檢查服務狀態

```bash
# 檢查 ASR
curl -H "X-API-Key: yuan-secret-key" \
  http://localhost:8000/asr/test

# 檢查 TTS
curl -H "X-API-Key: yuan-secret-key" \
  http://localhost:8000/tts/test
```

### 直接 TTS 調用

```bash
curl -X POST http://localhost:8000/tts/speak \
  -H "X-API-Key: yuan-secret-key" \
  -d "text=歡迎光臨" \
  -G

# 響應:
{
  "status": "success",
  "text": "歡迎光臨",
  "file_path": null
}
```

---

## 配置

編輯 `.env` 文件來配置 ASR 和 TTS：

```ini
# ASR 配置
ASR_PROVIDER=whisper
ASR_MODEL_SIZE=base      # tiny, base, small, medium, large
ASR_LANGUAGE=zh          # zh, en, ja, etc.

# TTS 配置
TTS_PROVIDER=pyttsx3
TTS_LANGUAGE=zh
TTS_RATE=150             # 50-300
TTS_VOLUME=1.0           # 0.0-1.0
```

---

## 性能指標

### ASR (Whisper)

| 模型大小 | 準確度 | 記憶體 | 速度 |
|---------|--------|--------|------|
| tiny | 低 | ~1GB | 最快 |
| base | 中 | ~1GB | 快 |
| small | 中-高 | ~2GB | 中等 |
| medium | 高 | ~5GB | 慢 |
| large | 最高 | ~10GB | 最慢 |

**推薦：** base 模型（平衡準確度和速度）

### TTS (pyttsx3)

- **延遲：** < 100ms（簡短句子）
- **CPUㄣ用：** 中等
- **記憶體：** < 50MB
- **語音質量：** 中等（機械感）

**推薦：** 用於系統級回應，不適合高質量語音應用

---

## 代碼示例

### 完整的語音對話流程

```python
from src.services.asr_service import ASRService
from src.services.tts_service import TTSService
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore

# 1. 初始化服務
asr = ASRService(model_size="base", language="zh")
tts = TTSService(language="zh", rate=150)
dm = DialogueManager(store=InMemorySessionStore())

# 2. 用戶說話（獲得音訊文件）
audio_file = "user_speech.wav"

# 3. ASR 轉錄
asr_result = asr.transcribe(audio_file)
user_text = asr_result["text"]
print(f"用戶說: {user_text}")

# 4. 對話管理器處理
session_id = "user123"
response = dm.handle(session_id, user_text)
print(f"店員回應: {response}")

# 5. TTS 播放
tts.speak(response)
```

### 使用實時流

```python
import pyaudio
import numpy as np

# 錄製 5 秒語音
audio_data = []
# ... 錄製邏輯 ...

# 轉換為字節
audio_bytes = np.array(audio_data).astype(np.int16).tobytes()

# 識別
result = asr.transcribe_bytes(audio_bytes, sample_rate=16000)
```

---

## 故障排除

### ❌ 問題：Whisper 模型下載失敗

```
FileNotFoundError: No such file or directory
```

**解決方案：**
```bash
# 手動下載模型
python -m pip install --upgrade openai-whisper
python -c "import whisper; whisper.load_model('base')"
```

### ❌ 問題：TTS 無聲音輸出

**解決方案：**
1. 檢查系統音量
2. 檢查音訊設備是否正確連接
3. 嘗試保存為文件測試：`tts.speak("test", save_to_file="test.wav")`

### ❌ 問題：ASR 識別效果差

**解決方案：**
1. 檢查音訊質量（採樣率應為 16000 Hz）
2. 降低背景噪音
3. 嘗試更大的模型：`ASRService(model_size="small")`

### ❌ 問題：API 返回 "error"

**解決方案：**
1. 檢查 .env 中的 API_KEY
2. 檢查 ASR/TTS 服務是否正常初始化
3. 查看服務器日誌

---

## 測試

### 運行 ASR/TTS 測試

```bash
pytest tests/test_asr_tts_integration.py -v

# 只運行 ASR 測試
pytest tests/test_asr_tts_integration.py::TestASRService -v

# 只運行 TTS 測試
pytest tests/test_asr_tts_integration.py::TestTTSService -v
```

### 集成測試

```bash
# 測試 API 端點
curl -H "X-API-Key: yuan-secret-key" http://localhost:8000/asr/test
curl -H "X-API-Key: yuan-secret-key" http://localhost:8000/tts/test
```

---

## 下一步改進

### 可選升級

1. **高質量 TTS**
   - 替換為 gTTS、Azure、或 Google Cloud TTS
   - 優勢：語音質量更高、更自然

2. **實時語音流**
   - 使用 WebRTC 或 WebSocket
   - 優勢：即時對話，無需等待

3. **多語言支持**
   - 自動語言檢測
   - 支持語言切換

4. **對話優化**
   - 使用 LLM 生成更自然的回應
   - 添加情感標記（快速/慢速）

5. **性能優化**
   - 模型量化以減少內存
   - 並行處理多個請求

---

## 配置參考

### 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| ASR_PROVIDER | whisper | 語音識別提供商 |
| ASR_MODEL_SIZE | base | Whisper 模型大小 |
| ASR_LANGUAGE | zh | 識別語言 |
| TTS_PROVIDER | pyttsx3 | 文字轉語音提供商 |
| TTS_LANGUAGE | zh | 語音語言 |
| TTS_RATE | 150 | 語速 (50-300) |
| TTS_VOLUME | 1.0 | 音量 (0.0-1.0) |
| API_KEY | yuan-secret-key | API 密鑰 |

---

## 總結

✅ **已完成**
- ASRService (Whisper) 實現完成
- TTSService (pyttsx3) 實現完成
- API 端點集成
- 環境配置更新
- 單元測試編寫

🟡 **可選改進**
- 更高質量的 TTS
- 實時語音流支持
- 多語言自動檢測
- 性能優化

**系統已準備好進行語音對話！** 🎙️

