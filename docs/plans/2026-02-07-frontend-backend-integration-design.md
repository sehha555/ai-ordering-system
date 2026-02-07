# 前後端整合設計

> 日期：2026-02-07
> 狀態：待實作

## 目標

接通 Next.js 前端與 FastAPI 後端，讓語音點餐完整流程可以跑：
語音 → ASR → LLM → 購物車更新 → TTS → 結帳 → 寫入訂單。

## 現有斷點

1. `voice_router.py` 的 DMAdapter 是空殼，沒接 LLM
2. 前端沒送 session_id，無法維持對話上下文
3. 結帳流程純前端，沒呼叫後端 API

## 設計決策

| 決策 | 選擇 | 理由 |
|------|------|------|
| voice_router 整合方式 | 直接接 LLM + ToolRegistry | 改動最少，最直接 |
| session_id 傳遞方式 | FormData 附帶 | 跟舊版一致，最簡單 |
| 結帳打後端程度 | 確認送出時打一次 | 夠用且改動小 |
| 取餐號碼 | 每日遞增，不設上限，最少兩位補零 | 01, 02, ... 99, 100 |
| 對話紀錄儲存 | SQLite + JSON 檔 | SQLite 做正式紀錄，JSON 方便翻閱調 prompt |
| 每輪結束清空 | 清 llm_history + 購物車 | 保持上下文容量，system prompt 固定不清 |

---

## Part 1：voice_router 改寫

- `voice_chat` 端點新增 `session_id: str = Form(...)` 參數
- 砍掉假的 DMAdapter，改寫為真的呼叫 `_llm_caller.run_turn()`
- 帶入 `SYSTEM_PROMPT`、`session["llm_history"]`、ToolRegistry 的 schema 和 tool_map
- 呼叫完 LLM 後，從 `_session_store` 讀取購物車資料，組成 `cart_update` 事件
- StreamingOrchestrator 介面微調：`process_audio_stream` 多傳 `session_id`

### 資料流

```
前端 FormData(file + session_id)
  → voice_router 讀取
  → ASR 辨識文字 → SSE: transcription
  → LLM + ToolRegistry 處理 → SSE: cart_update（從 session 讀購物車）
  → TTS 串流音訊 → SSE: audio_chunk
```

## Part 2：前端 VoiceController 改動

- `sendAudioToServer` 的 FormData 加 `session_id`
- SSE 解析、VAD、音訊播放不變

## Part 3：結帳 API + 取餐號碼

### 新端點 `POST /api/checkout`

接收：
- `session_id`: str
- `dine_type`: "dine-in" | "take-out"
- `payment_method`: "cash" | "mobile"

處理：
1. 從 `_session_store` 讀取購物車
2. 寫入 `orders.db`
3. 取餐號碼：`SELECT MAX(order_number) FROM orders WHERE date = today` + 1
4. 儲存對話紀錄（SQLite + JSON 檔）
5. 清空 session 的 `llm_history` 和購物車
6. 回傳 `{ order_number, total, status }`

### 取餐號碼規則

- 每日 00:00 重置回 01
- 最少兩位數補零（01, 02, ... 99, 100, 101）
- 不設上限

## Part 4：對話紀錄儲存

### SQLite 表

```sql
CREATE TABLE conversation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    order_number TEXT,
    messages TEXT NOT NULL,  -- JSON: 完整 llm_history
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### JSON 檔案

- 路徑：`logs/{date}/{session_id}.json`
- 例如：`logs/2026-02-07/session-1738900000000.json`
- 內容包含：session_id, order_number, cart, total, dine_type, messages, created_at
- 按日期分資料夾
- `logs/` 加入 `.gitignore`

## Part 5：完整資料流

```
使用者說話
  → VAD 偵測 → 開始錄音 → 靜音停止
  → FormData(file + session_id) POST /api/voice-chat
  → ASR 辨識 → SSE: transcription
  → LLM + ToolRegistry(session_id) → 更新購物車
  → 從 session_store 讀購物車 → SSE: cart_update
  → TTS 串流 → SSE: audio_chunk
  → 前端更新畫面 + 播放語音

使用者按結帳
  → 選用餐方式 → 選付款 → 確認送出
  → POST /api/checkout(session_id, dine_type, payment_method)
  → 寫訂單 + 存對話紀錄 + 清 session + 回傳取餐號碼
  → 前端顯示取餐號碼
  → 「新訂單」→ resetSession() 產生新 session_id
```

## 改動檔案

| 檔案 | 動作 | 說明 |
|------|------|------|
| `src/api/voice_router.py` | 改寫 | DMAdapter 接 LLM，加 session_id |
| `src/services/streaming_orchestrator.py` | 修改 | process_audio_stream 傳 session_id |
| `src/api/app.py` | 新增端點 | POST /api/checkout |
| `src/repository/order_repository.py` | 修改 | 新增 conversation_logs 表、取餐號碼查詢 |
| `src/frontend_next/components/VoiceController.tsx` | 微改 | FormData 加 session_id |
| `src/frontend_next/components/CheckoutFlow.tsx` | 修改 | 確認送出打 API |
| `.gitignore` | 修改 | 加 logs/ |
