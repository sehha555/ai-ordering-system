# 源飯糰 AI 語音點餐系統 - Voice Dashboard 實作藍圖

本文件詳細說明如何將現有的 FastAPI 系統升級為現代化的 **Voice Dashboard (Next.js + FastAPI)** 架構。

---

## 🎨 1. 設計規格 (Design Specs)

### 1.1 視覺風格 (Visual Identity)
- **主題**：現代極簡餐飲科技 (Modern F&B Tech)
- **色票 (Color Palette)**：
  - **Primary (主色/波形/按鈕)**: `#729DAD` (灰藍綠)
  - **Secondary (互動/漣漪)**: `#7AA8BB` (亮灰藍)
  - **Text/Accent (文字/深色)**: `#6C8F9C` (深灰藍)
  - **Background**: `#F5F7F8` (極淺冷灰) 或 `#FFFFFF` (純白)
  - **Card/Receipt**: `#FFFFFF` with light `#729DAD` shadow

### 1.2 介面佈局 (Layout)
- **中央舞台 (Center Stage)**：
  - 放置動態音頻波形 (Audio Visualizer)。
  - 狀態與顏色：
    - 🔵 **Idle (待命)**: `#729DAD` 緩慢流動的液態圓環。
    - 🟢 **Listening (聆聽)**: `#7AA8BB` 隨音量擴散的漣漪。
    - 🟣 **Thinking (思考)**: `#6C8F9C` 快速旋轉聚合。
    - 🟠 **Speaking (說話)**: `#729DAD` 隨 TTS 音頻振幅跳動。
- **右側面板 (The Receipt)**：
  - 標題：「目前餐點」。
  - 列表：使用 Framer Motion 實現 `AnimatePresence`，新增商品時「滑入」效果。
  - 底部：總金額 (大字體)。

---

## 🛠️ 2. 前端實作計畫 (Next.js)

### 2.1 技術棧
- **Framework**: Next.js 14+ (App Router)
- **Styling**: Tailwind CSS
- **State Management**: Zustand (管理錄音狀態、購物車數據)
- **Audio Processing**:
  - `AudioContext` (Web Audio API) for Visualizer & Playback.
  - `MediaRecorder` API for capturing voice.
- **Protocol**: Server-Sent Events (SSE) for real-time streaming.

### 2.2 核心元件 (`src/components/`)
1.  **`AudioVisualizer.tsx`**:
    - 使用 Canvas API 或簡單的 CSS Animation 繪製波形。
    - 接收 `audioData` (頻率陣列) props 來驅動動畫。
2.  **`VoiceController.tsx`**:
    - 負責麥克風權限、VAD (簡單音量偵測)、錄音與停止。
    - 處理 SSE 連線，解析後端回傳的事件 (`transcription`, `cart_update`, `audio_chunk`)。
    - 負責將接收到的 PCM/MP3 chunks 餵給 `AudioContext` 播放。
3.  **`LiveReceipt.tsx`**:
    - 顯示購物車內容。
    - 訂閱 Zustand store 中的 `cart` 狀態。

### 2.3 資料流 (Data Flow)
1.  **User Speaks** -> `VoiceController` 錄音 -> `Blob`。
2.  **POST /api/voice-chat** -> 傳送 Audio Blob。
3.  **SSE Response** (Server -> Client):
    - `event: transcription` -> 更新 UI 顯示用戶文字。
    - `event: thinking` -> 切換 Visualizer 狀態。
    - `event: cart_update` -> 更新 Zustand `cart` -> 更新 `LiveReceipt`。
    - `event: audio_chunk` -> 放入播放 Queue -> `AudioContext` 播放 -> Visualizer 跳動。

---

## ⚙️ 3. 後端實作計畫 (FastAPI)

### 3.1 架構調整
- 新增 `src/api/voice_router.py`。
- 新增 `src/services/streaming_manager.py` (處理 SSE 邏輯)。

### 3.2 TTS 抽象層 (`src/services/tts_interface.py`)
為了保留彈性 (EdgeTTS <-> OpenAI <-> Custom)，建立統一介面：

```python
class TTSModel(ABC):
    @abstractmethod
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (PCM or MP3 frames)"""
        pass
```

- **實作 1**: `EdgeTTSModel` (預設) - 使用 `edge-tts` 庫的 stream 功能。
- **實作 2**: `OpenAITTSModel` (備用) - 使用 OpenAI API stream。

### 3.3 新增 API Endpoint
`POST /api/voice-chat`
- **Input**: `UploadFile` (audio/wav or audio/webm)
- **Process**:
  1.  儲存暫存檔 -> ASR Service (Whisper) -> Text。
  2.  Text -> DialogueManager (Existing) -> Response Text & Cart JSON。
  3.  Response Text -> TTS Model -> Audio Chunks。
- **Output**: `StreamingResponse` (media_type="text/event-stream")

### 3.4 SSE 事件格式
```text
event: transcription
data: {"text": "我要一個飯糰"}

event: thinking
data: {}

event: cart_update
data: {"items": [...], "total": 100}

event: audio_chunk
data: <Base64 Encoded Audio Bytes>
```

---

## 🚀 4. 執行步驟 (Execution Steps)

1.  **Backend Setup**:
    - 定義 TTS 抽象介面。
    - 實作 SSE Endpoint。
    - 測試 API 能否回傳串流數據。
2.  **Frontend Setup**:
    - 初始化 Next.js 專案。
    - 設定 Tailwind 與品牌色。
    - 實作錄音與 SSE 接收邏輯。
    - 整合 Audio Visualizer。
3.  **Integration**:
    - 前後端連調。
    - 優化延遲 (Latency Tuning)。

