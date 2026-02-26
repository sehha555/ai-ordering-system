# MVP 上線 Roadmap — 源飯糰 AI 語音點餐系統

**日期**：2026-02-24
**狀態**：已確認，進入執行階段
**作者**：AI Ordering System Team

---

## 背景與決策摘要

**專案**：源飯糰 AI 語音點餐系統
**現況**：98% 完成，192 tests 全通過（124 後端 + 68 前端），MVP 就緒

| 決策 | 結論 |
|------|------|
| 部署場景 | 單店 MVP 驗證 → 再擴展 |
| 前後端託管 | Zeabur（前後端都放） |
| GPU 模型策略 | dev 用本地模型（SenseVoice + Qwen3），prod 用雲端 API（Whisper + 雲端 LLM 待選型） |
| 域名 | 先用 Zeabur 免費子網域（自帶 HTTPS） |
| 使用介面 | 店內平板／大螢幕 |
| 時間 | 1 個月內上線 |
| LLM 選型 | 待定，架構不綁死（GPT-4o-mini / Claude Haiku / Gemini Flash 等候選）|
| 成功標準 | 顧客完成率（語音完成完整點餐不需人工介入）+ 店員滿意度 |
| 月預算 | ~$55–65（Zeabur $5–15 + OpenAI API ~$50）|

---

## 核心策略

> **「地端穩定 → 加雲端抽象層 → 部署上線」**

先在開發主機（RTX 5070 Ti）上用本地模型驗證完整 UX 流程，確認穩定後，上雲只是純粹的基礎設施搬遷，不涉及任何業務邏輯改動。

---

## 時程總覽

| Phase | 內容 | 時間 |
|-------|------|------|
| Phase 1 | 地端驗證 | Week 1–2 |
| Phase 2 | 雲端 API 抽象層 + Zeabur 部署 | Week 3 |
| Phase 3 | 生產強化 + LLM 選型 | Week 3 後半 |
| Phase 4 | 店面實測 | Week 4 |

---

## Phase 1：地端驗證（Week 1–2）

**目標**：在開發主機上用平板實際操作，驗證完整語音點餐流程。

### 1.1 平板連線環境

- 開發主機跑 FastAPI（port 8000）+ Next.js（port 3000）
- 平板透過區網連到主機 IP
- HTTPS 處理（瀏覽器 `getUserMedia` 需要 HTTPS），方案二擇一：
  - 自簽憑證（平板手動信任一次）
  - Chrome flag `chrome://flags/#unsafely-treat-insecure-origin-as-secure`（MVP 最快）

### 1.2 端到端流程驗證

驗證完整語音點餐流程：開口 → ASR 辨識 → LLM 理解 → TTS 回覆 → 加入購物車 → 結帳

驗證場景清單：

| 場景 | 範例 |
|------|------|
| 單品點餐 | 「一個招牌飯糰」 |
| 多品項 | 「一個招牌飯糰加一杯豆漿」 |
| 客製化 | 「飯糰不要辣」 |
| 修改購物車 | 「把豆漿換成紅茶」 |
| 查詢菜單 | 「有什麼飲料」 |
| 結帳 | 「結帳」「算錢」 |
| 離題處理 | 「今天天氣好嗎」 |
| ASR 辨識錯誤容錯 | 常見誤辨字詞的自動修正 |

### 1.3 Prompt 調優

- **語氣調整**：台灣口語、親切自然
- **Tool calling 穩定性**：確認 Qwen3 在各場景都能正確呼叫工具
- **ASR 容錯 prompt**：讓 LLM 自動修正常見辨識錯誤

### 1.4 Bug 修復

- 記錄所有實際操作中發現的問題
- 立即修復，跑測試確認不 break 其他功能

**Phase 1 產出**：一份「地端驗證報告」，記錄測試結果、發現的問題、修復內容。

---

## Phase 2：雲端 API 抽象層 + Zeabur 部署（Week 3）

**目標**：讓系統能在無 GPU 環境跑起來，部署到 Zeabur。

### 2.1 ASR 雲端 API 支援

- 新增 `ASRInterface` ABC（統一 `transcribe` 介面）
- 新增 `WhisperAPIService`，呼叫 OpenAI Whisper API
- 統一介面簽名：`transcribe(audio_bytes: bytes) -> dict`
  - 現況：orchestrator 傳 bytes，service 收 path，趁機一併統一
- 擴充 `create_asr_service()` 工廠：新增 `elif backend == "whisper_api"` 分支
- 將現有 `SenseVoiceService` / `ASRService` 包裝成符合 ABC 的形式

**工作量估計**：約 50 行新程式碼，改動 2–3 個檔案。

### 2.2 LLM 環境變數切換

現有架構已採用 OpenAI 相容格式，切換雲端 LLM 幾乎只需改 `.env.prod`：

```env
LLM_BASE_URL=https://api.openai.com/v1/chat/completions  # 或其他供應商
LLM_MODEL=gpt-4o-mini  # 待選型後填入
```

其他調整：
- `settings.py` 補充 `OPENAI_API_KEY` 欄位
- System prompt 調整：移除 Qwen3 專屬標記（如 `/no_think`），prod 使用乾淨版本
- 保留 Qwen3 regex fallback parser（不影響其他 LLM，但提供安全網）

**工作量估計**：幾乎零程式碼改動，主要是 prompt 微調 + 環境變數設定。

### 2.3 Settings 擴充

在 `settings.py` 新增以下欄位：

```python
OPENAI_API_KEY: str | None = None
ANTHROPIC_API_KEY: str | None = None  # 預留
WHISPER_MODEL: str = "whisper-1"
# ASR_BACKEND 新增選項："whisper_api"
```

### 2.4 Zeabur 部署

- 建立 `zeabur.json` 或直接用 Zeabur Dashboard 連接 GitHub repo
- 後端：使用現有 `Dockerfile.backend`（移除 GPU 相關設定）
- 前端：使用現有 `Dockerfile.frontend`

環境變數在 Zeabur Dashboard 設定（不進 git）：

| 變數 | 說明 |
|------|------|
| `ENVIRONMENT` | `prod` |
| `API_REWRITE_TARGET` | `https://[backend-service].zeabur.app` |
| `LLM_BASE_URL` | 雲端 LLM API endpoint |
| `LLM_MODEL` | 選定的模型 ID |
| `OPENAI_API_KEY` | OpenAI API 金鑰 |
| `REDIS_URL` | Zeabur Redis add-on 連線字串 |
| `CORS_ORIGINS` | `https://[frontend-service].zeabur.app` |

基礎設施：
- **HTTPS**：Zeabur 免費子網域自帶，零設定
- **Redis**：用 Zeabur Redis add-on，一鍵啟用

### 2.5 部署驗證

- 在雲端環境跑一輪 Phase 1 的驗證場景
- 確認延遲可接受（目標：一輪對話 < 5 秒）
- 確認 CORS、HTTPS、SSE streaming 均正常

**Phase 2 產出**：可存取的 Zeabur URL + 雲端驗證通過。

---

## Phase 3：生產強化 + LLM 選型（Week 3 後半）

### 3.1 LLM 選型比較

**候選模型**：

| 模型 | 特點 |
|------|------|
| GPT-4o-mini | 便宜、tool calling 穩定、中文能力好 |
| Claude Haiku | 便宜、推理能力強 |
| Gemini Flash | Google 生態、免費額度高 |
| 開源 hosted（Together.ai / Fireworks） | 可跑 Qwen3 等開源模型 |

**比較維度**（依重要性排序）：

1. Tool calling 穩定性（最重要）
2. 中文理解能力
3. 延遲
4. 價格
5. 台灣口語處理能力

**方法**：使用現有 BDD 測試場景跑各 LLM，比較通過率。

### 3.2 安全強化

- 確認 API_KEY 認證已啟用
- 確認 `.env.prod` 已在 `.gitignore`
- Zeabur 環境變數不含機密資料的 fallback 預設值
- CORS 只允許前端域名

### 3.3 TTS 快取清理

- 實作 TTSCacheCleanup：定期清理過期快取檔
- 使用簡單的 LRU 或 TTL 策略即可

### 3.4 基本監控

MVP 階段不上 Prometheus + Grafana（過重），採用輕量方案：
- 使用 Zeabur 內建 log viewer + 現有 loguru 結構化日誌
- 新增簡單的 `/metrics` endpoint，回傳：
  - 今日訂單數
  - 平均對話輪數
  - ASR / LLM / TTS 平均延遲（已有 PerfTimer 基礎）

---

## Phase 4：店面實測（Week 4）

### 4.1 硬體準備

- 店內平板／大螢幕 + 穩定網路
- 平板瀏覽器打開 Zeabur 前端 URL
- 可考慮用 Android kiosk mode 鎖定成單一 App

### 4.2 店員訓練

- 教店員了解系統運作方式與常見問題處理
- 準備 fallback 方案：系統故障時切回人工點餐

### 4.3 軟上線

- 先在非尖峰時段測試
- 收集真實顧客使用數據
- 記錄：完成率、中斷點、常見失敗場景

### 4.4 回饋收集

- 顧客完成率追蹤（成功點餐 / 總嘗試）
- 店員每日回饋（簡單表單或口頭）
- 系統日誌分析（哪些對話失敗、原因為何）

**Phase 4 產出**：MVP 驗證報告 — 決定是否繼續投資。

---

## 刻意延後的項目（Post-MVP）

| 項目 | 延後原因 | 何時再做 |
|------|----------|----------|
| PostgreSQL | 單店 SQLite 夠用 | 有並發寫入需求時 |
| Prometheus + Grafana | MVP 階段過重 | 多店／正式營運時 |
| 模型實測（BreezyVoice / ElevenLabs / Qwen2.5-Omni） | 先驗證概念再優化模型 | MVP 成功後 |
| Nginx 反向代理 | Zeabur 已處理 | 自建機房時 |
| 自訂域名 | 先用免費子網域 | 正式營運時 |
| 多店支援 | 不在 MVP 範圍 | 第一間店驗證成功後 |
| 手機 QR Code 掃碼點餐 | 先專注固定裝置 | Phase 2 擴展 |

---

## 現有架構評估

### 工程改動量總覽

| 模組 | 改動量 | 說明 |
|------|--------|------|
| LLM | 幾乎零 | 已用 OpenAI 相容格式，改 `.env` 即可 |
| ASR | 中等（約 50 行） | 新增 WhisperAPIService + ABC 介面 |
| TTS | 不用動 | Edge TTS 已是雲端服務 |
| Settings | 補 3–4 個欄位 | API Key + Whisper Model |
| Orchestrator | 不用動 | 完全解耦 |
| Docker | 微調 | 移除 GPU 設定，供 prod 使用 |
| Zeabur 配置 | 新增 | `zeabur.json` 或 Dashboard 設定 |

### 已有的好基礎

- Docker 多階段構建（backend + frontend 都有）
- CI/CD：GitHub Actions（ruff + pytest + vitest）
- 環境分層：`.env.dev` / `.env.prod` / `settings.py` Pydantic Settings
- `API_REWRITE_TARGET` 環境變數化（前端 proxy 指向可配置）
- 健康檢查：`/healthz` + `/readyz`
- 結構化日誌：loguru + PerfTimer

### 注意事項（潛在的坑）

| 問題 | 處理時機 |
|------|----------|
| `transcribe()` 介面不一致（orchestrator 傳 bytes，service 收 path） | Phase 2.1 統一 |
| `LLMToolCaller.__init__` 預設值 hardcode | 確認呼叫點已接 settings |
| `.env.prod` 未在 `.gitignore` | Phase 2 前確認 |
| Zeabur 部署後 CORS_ORIGINS 需更新 | 部署後立即設定 |

---

## 成本估算

### 月度營運成本（基準：200 單／天）

| 項目 | 估計月費 |
|------|----------|
| Zeabur 後端 | ~$5–10 |
| Zeabur 前端 | ~$0–5（靜態站幾乎免費） |
| Zeabur Redis | ~$0–5 |
| OpenAI Whisper API | ~$18 |
| 雲端 LLM API | ~$30（依選型） |
| Edge TTS | 免費 |
| **合計** | **~$55–65／月** |

### 成本優化路徑（未來）

- 流量大了 → 買店內主機自建，省雲端 API 費
- LLM 選型確定後 → 談量價或換更便宜的模型
- ASR 可考慮 Groq Whisper（免費／極便宜 + 超快）

---

## 風險與 Mitigation

| 風險 | 影響 | 對策 |
|------|------|------|
| 雲端 LLM tool calling 行為與 Qwen3 不同 | Prompt 需要重調 | 用 BDD 測試場景驗證，保留 fallback parser |
| 店內網路不穩 | 系統無法使用 | 準備離線 fallback 方案（退回人工點餐） |
| Whisper API 中文辨識品質不如 SenseVoice | 辨識率下降 | 保留 ASR 後處理修正表，地端驗證時建立 baseline |
| 顧客不習慣語音點餐 | 完成率低 | 店員旁邊輔助引導，收集使用者行為以改善 UX |
| 延遲太高（> 5 秒／輪） | UX 差 | 選低延遲 LLM + Whisper API（或 Groq），TTS 預快取 |

---

## 修改紀錄（Audit Trail）

- 2026-02-24：初版建立，MVP 上線 Roadmap（四階段計畫）#AuditTrail by claude-code
