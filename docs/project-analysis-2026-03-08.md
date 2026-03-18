# AI 點餐系統架構審查報告

> 審查日期：2026-03-08
> 審查範圍：後端架構、前端、LLM Pipeline、ASR/TTS、菜單管理、測試、部署、安全
> 系統定位：早餐店地端單機 AI 語音點餐系統

---

## 1. 現況總結

### 1.1 後端架構（完成度：85%）

**優點：**
- FastAPI + lifespan 管理生命週期，啟動驗證（`_validate_startup`）、LLM/TTS 預熱、背景 session 清理一應俱全
- Session Store 有 Protocol 介面 + InMemory/Redis 雙實作 + 工廠函式自動 fallback，設計扎實
- Rate limiting（slowapi）已按端點分級：對話 10/min、結帳 5/min、查詢 60/min
- 健康檢查分為 liveness（`/healthz`，零依賴）和 readiness（`/readyz`，檢查 SQLite/Redis/LLM/ASR），符合 K8s 規範
- Request ID middleware 提供端到端追蹤能力
- DB 自動備份（每日一份，保留 7 天）+ 索引優化
- 訂單號碼使用 `BEGIN IMMEDIATE` 防競態

**問題：**
- `app.py` 職責過重（約 800 行）：同時包含路由定義、服務初始化、容器注入、業務邏輯。服務初始化散落在 module-level，不利於測試和模組化
- `_run_dialogue_turn` 是 sync 函式但被 async 端點呼叫（`run_turn` 內部用 `requests.post` 同步阻塞），SSE 端點有獨立的 async 路徑但非 SSE 端點仍可能阻塞 event loop
- 服務容器（`container.py`）使用 module-level 變數注入，屬於 service locator 反模式，但對此規模的單機系統尚可接受
- 舊版 `/dialogue/voice` 端點仍保留（寫臨時檔 + subprocess ffmpeg），與新版 SSE `/api/voice-chat`（pipe stdin）功能重複

### 1.2 前端 — Next.js 16 + React 19（完成度：80%）

**優點：**
- Zustand store 結構清晰，action 命名明確
- SSE 解析正確處理跨 chunk 的 event/data 分割問題（`parseSSELines` 回傳 currentEvent）
- 音訊播放使用 `<audio>` + Blob URL 事件鏈，規避了 `decodeAudioData` 對 MP3 的已知問題
- VAD 有自適應校準（環境噪音取樣 + 倍數閾值）、最大錄音 30s 保護、silence timeout
- 自動追問機制（speaking -> idle 後 3 秒無語音 -> 送文字詢問）
- Framer Motion 動畫品質高，品項進出、球體切換流暢
- 結帳流程支援語音觸發（`finalize_order`）和手動按鈕雙路徑

**問題：**
- `VoiceController.tsx`（737 行）過於龐大，混合了 VAD 邏輯、SSE 解析、音訊錄製、播放控制、自動追問、鍵盤快捷鍵。建議拆分為獨立 hooks
- `aiReply` 在 store 中沒有清除機制的完整閉環 — `handlePlaybackComplete` 清除了，但若播放鏈異常中斷則可能殘留
- `page.tsx` 中 `OrderTicket` 的 key 使用 `item.name`，同名品項（如兩份不同規格的飯糰）會導致動畫問題
- session ID 使用 `Date.now()` 生成，多個分頁同時開啟可能碰撞。建議用 `crypto.randomUUID()`
- 前端缺乏離線體驗（navigator.onLine 只在 sendAudio 檢查）
- Admin 頁面（menu/orders）存在但未見認證保護

### 1.3 LLM Pipeline（完成度：90%）

**優點：**
- Few-shot priming 設計精良：7 個不與 test case 重疊的 demo，覆蓋齊全 call / 缺資訊追問 / 結帳 / 俗稱 / ok:false 反饋 / 邊界保護
- Response Template 架構：tool ok:true 後由 code 構建回覆，消除模型生成不穩定性
- 幻覺雙重防護：assistant prefill "好，" + regex 清除系統錯誤道歉
- System prompt 結構經過精心調校：固定前綴 + 動態尾段（售完/營業狀態），最大化 prefix cache 命中率
- Tool calling 的 content fallback 解析（Qwen 格式 `<tool_call>` tag），增加魯棒性
- TTS cache 預熱高頻回覆，TTFA 接近零
- Streaming orchestrator 的分句策略（MIN/MAX 字數 + 標點切分）設計合理

**問題：**
- `run_turn` 和 `run_turn_stream` 有大量重複邏輯（message 構建、tool call 循環、history 更新），約 60% 程式碼相似
- `_post` 使用同步 `requests.post`，`_post_async` 透過 `asyncio.to_thread` 包裝，但 `run_turn`（同步版）在 async context 中被 `asyncio.to_thread` 再包一層會造成 thread pool 壓力
- Sampling 參數（temperature=0.3, top_p=0.8, top_k=20, min_p=0.01）散落在兩個方法中，未抽為常數
- `max_steps=4` 是硬上限，但缺少配置化方式

### 1.4 ASR/TTS（完成度：85%）

**優點：**
- ASR 支援 SenseVoice 和 Qwen3-ASR 雙後端，工廠模式切換
- ASR 後處理（`asr_postprocess.py`）包含 opencc 簡轉繁 + 領域詞彙修正表
- TTS 支援 Edge TTS 和 Qwen3-TTS，Qwen3-TTS 載入失敗自動 fallback Edge TTS
- Edge TTS 零 VRAM、免費，適合地端部署
- TTS cache 正規化 key（去標點）提升命中率

**問題：**
- ASR 使用 file path 介面，voice_router 中 ASRAdapter 每次都寫臨時檔再讀取，存在不必要的磁碟 I/O
- SenseVoice 的 `_patch_funasr_tiktoken` 是針對特定版本的 workaround，未來升級可能失效
- TTS cache 是純 in-memory，重啟後需重新預熱。地端單機可接受但應記錄此限制
- `confidence: 0.95` 是 ASR 服務硬編碼的假值，並非模型真實信心度

### 1.5 菜單管理（完成度：85%）

**優點：**
- 售完管理有連動規則引擎（品項級 + 分類級 + 套餐可用性 + 米種/饅頭/麵種選項限制）
- Admin API 完整：品項/分類售完、營業時間、強制開關、一鍵恢復
- 訂單 SSE 即時推送（`OrderBroadcaster`）支援多訂閱者 + heartbeat + 滿隊列丟棄
- 菜單領域指南（Triad Engine Format B）壓縮 token 數量，飲品去重、飯糰含成分

**問題：**
- 售完狀態目前是 in-memory（`menu_state_service`），重啟後歸零。生產環境需要持久化
- Admin 端點完全沒有認證保護（無 API Key 依賴），任何人可以修改菜單狀態
- `menu_all.json` 是靜態檔案，新增品項需修改檔案重啟。缺乏動態菜單管理

### 1.6 測試（完成度：70%）

**優點：**
- 34 個測試檔案、約 3,946 行測試程式碼，覆蓋面廣
- 使用 pytest-bdd 進行行為驅動測試，12 個 feature 檔案
- 安全測試（prompt injection）、合約測試、整合測試均有覆蓋
- Benchmark 系統成熟：config.yaml + adapters + metrics + reports，repeat=3 機制控制波動

**問題：**
- 前端測試檔案存在（4 個 component + 1 個 store），但未確認實際通過狀態
- 缺乏 SSE 串流端點的整合測試（`/api/voice-chat` 和 `/api/text-chat`）
- 缺乏負載測試 / 壓力測試（對地端單機而言不緊急但需要了解上限）
- E2E smoke test 使用 monkeypatch 注入測試 DB，但 module-level singleton 的注入方式脆弱
- 缺乏 TTS cache、streaming orchestrator 的單元測試

### 1.7 部署（完成度：75%）

**優點：**
- Dockerfile 使用 multi-stage build：backend 2-stage（deps + runtime）、frontend 3-stage（deps + builder + standalone runner）
- docker-compose 分層設計：base + dev/prod/hybrid override
- Production compose 配置了 Redis + GPU reservation + restart policy + healthcheck
- Frontend standalone 模式（~100MB vs ~500MB），非 root 執行
- `.env.example` 完整，覆蓋所有可配置項

**問題：**
- LM Studio 是外部依賴但不在 docker-compose 管理範圍內（因為是桌面應用），需要文件說明啟動順序
- 缺少 CI/CD pipeline 定義（GitHub Actions / GitLab CI）
- `orders.db` 的 volume mount 在 prod compose 中是 `orders_data:/app/orders.db`，但 SQLite 不適合 Docker volume 的方式，應該 mount 整個目錄
- Dockerfile.backend 未複製 `tools/menu/` 目錄下的菜單資料檔案（`menu_all.json` 等在 `src/tools/menu/` 下，已被 `COPY src/ ./src/` 涵蓋 — 但 `orders.db`、`logs/`、`backups/` 的 volume 策略未明確）
- 無 log rotation / log shipping 方案

### 1.8 安全（完成度：60%）

**優點：**
- API Key 認證機制存在，prod 環境強制要求設定
- CORS 從設定檔讀取，不是 wildcard
- TTS 播放端點有路徑穿越防護（`os.path.realpath` + 目錄前綴檢查）
- Tool execution 有 allowed_args 白名單過濾
- Order ID 格式驗證（`^[A-Z0-9-]+$`，長度上限 20）
- Prompt injection BDD 測試存在
- SQL 查詢使用參數化（無 SQL injection 風險）

**問題：**
- **Admin 端點完全無認證**（`/admin/*`）— 這是最關鍵的安全缺口
- API Key 在 dev 模式下完全停用（`get_api_key` 回傳 "dev"），前端 SSE 端點的 `get_api_key_optional` 永遠不驗證
- Session ID 由前端生成（`Date.now()`），可預測且可偽造。理論上可以劫持他人 session
- 無 HTTPS 配置（地端區網可能可接受，但行動支付場景需要）
- Rate limiting 使用 IP 為 key，地端區網內所有裝置可能共享同一 IP
- 無 CSRF 保護（POST 端點接受任何來源）
- 無輸入長度限制（`user_text` 可以很長，可能導致 LLM token 溢出）

---

## 2. 可補強的地方

### P0 — 必做（上線前必須完成）

| # | 項目 | 說明 | 預估工作量 |
|---|------|------|-----------|
| 1 | Admin 認證 | `/admin/*` 端點加上認證（至少 API Key，建議 session-based） | 2-4h |
| 2 | Session ID 安全 | 後端生成 session ID（UUID4），前端僅保存。或至少驗證格式 | 2h |
| 3 | 售完狀態持久化 | 當前 in-memory，重啟歸零。持久化到 SQLite 或 JSON 檔案 | 3-4h |
| 4 | 輸入長度限制 | `user_text` 加上字數上限（如 500 字），防止 token 溢出 | 1h |
| 5 | 錯誤恢復機制 | 前端 SSE 連線異常時的 retry + 使用者提示完善（目前有部分但不完整） | 3h |
| 6 | LM Studio 啟動依賴 | readiness check 失敗時的 graceful degradation（目前 LLM 不可用會 500） | 2h |

### P1 — 建議（顯著提升品質和可靠度）

| # | 項目 | 說明 | 預估工作量 |
|---|------|------|-----------|
| 7 | app.py 拆分 | 將服務初始化、路由定義、業務邏輯分離。至少把 checkout/voice/text dialogue 拆成獨立 router | 4-6h |
| 8 | VoiceController 拆分 | 將 VAD、錄音、SSE 處理、自動追問拆為獨立 hooks | 4-6h |
| 9 | SSE 端點整合測試 | 模擬完整的 voice-chat / text-chat SSE 流程 | 4h |
| 10 | 監控和告警 | Perf stats 已有收集，但缺乏持久化和告警。對地端可用 loguru + 簡單閾值告警 | 4h |
| 11 | 刪除舊版端點 | `/dialogue/voice`、`/dialogue/llm`、`/dialogue/text` 與 SSE 端點功能重複 | 2h |
| 12 | 自動重啟腳本 | LM Studio 或後端異常退出時的 watchdog / systemd service | 2-3h |
| 13 | 前端 OrderTicket key 修正 | 使用唯一 index 而非 `item.name` 避免同名品項動畫衝突 | 30min |
| 14 | LLM 同步/異步統一 | `run_turn` 和 `run_turn_stream` 重複邏輯抽為共用方法 | 3h |

### P2 — Nice-to-have（長期改進）

| # | 項目 | 說明 |
|---|------|------|
| 15 | ASR bytes 介面 | 讓 ASR service 直接接受 bytes，省去臨時檔 I/O |
| 16 | HTTPS | 地端部署可用 mkcert 自簽憑證 + nginx reverse proxy |
| 17 | 日誌結構化 | Production 模式下的 JSON log + log rotation（loguru 已支援） |
| 18 | 多語言支援 | 目前硬編碼繁體中文，長期可能需要支援客語/英語 |
| 19 | 離線模式 | 前端 PWA + Service Worker 快取靜態資源 |
| 20 | 購物車持久化 | 瀏覽器 refresh 後購物車消失（目前僅存 session store） |

---

## 3. 離生產環境的差距

### 必須完成的項目清單

#### 基礎設施層
- [ ] Admin 端點認證保護
- [ ] 售完狀態持久化（重啟不歸零）
- [ ] LM Studio 啟動順序文件化 + readiness 等待機制
- [ ] 啟動腳本（`start.ps1` 已存在，確認涵蓋 LM Studio + backend + frontend 完整流程）
- [ ] 資料庫 volume mount 策略確認（SQLite 檔案級鎖定 + Docker volume 相容性）

#### 安全層
- [ ] Session ID 改為後端生成或至少加密簽名
- [ ] 使用者輸入長度限制（text、audio file size）
- [ ] Admin 認證（基本帳密或 token）

#### 可靠度層
- [ ] LLM 不可用時的降級策略（而非直接 500）
- [ ] TTS 失敗時的降級（純文字回覆）— 目前有 try/except 但前端未處理無音訊情況
- [ ] ASR 失敗時的重試提示（已有但需確認完整鏈路）
- [ ] 前端 SSE 斷線重連機制

#### 測試層
- [ ] SSE 串流端點整合測試
- [ ] 前端測試確認全部通過
- [ ] 手動端到端測試流程文件化（從開機到完成一筆訂單）

#### 部署層
- [ ] 一鍵部署腳本（含 LM Studio 模型下載 + 後端 + 前端）
- [ ] 環境變數檢查清單（`.env.prod` 範本 + 必填項驗證）
- [ ] 備份還原流程驗證

---

## 4. 技術債

### 高優先
1. **app.py 巨型檔案**：800+ 行，混合了路由、初始化、業務邏輯。建議拆為 `app.py`（初始化）+ `checkout_router.py` + `legacy_router.py`
2. **VoiceController.tsx 巨型元件**：737 行，建議拆為 `useVAD`、`useSSE`、`useRecording`、`useAutoPrompt` 等 hooks
3. **LLM caller 同步/異步重複**：`run_turn` 和 `run_turn_stream` 約 60% 程式碼重複
4. **舊版 dialogue 端點**：`/dialogue/voice`、`/dialogue/llm`、`/dialogue/text` 已被 SSE 端點取代但仍保留

### 中優先
5. **DialogueManager 雙角色**：既是舊版規則引擎（`handle` 方法，基於 regex 路由 + pending_frames 狀態機），又作為 LLM pipeline 的支援類。兩套系統並存增加理解成本
6. **module-level singleton 初始化**：`order_repo = OrderRepository()` 在 import 時執行，測試時需要 monkeypatch 多個模組
7. **ASR confidence 假值**：`confidence: 0.95` 硬編碼，誤導監控和日誌分析
8. **`_TOOL_STATUS_MAP` 過時**：包含 `add_to_cart`（舊 tool 名）和 `get_cart_summary`（已從 schema 移除）

### 低優先
9. **TTS cache 不支援 eviction**：cache 只增不減，長期運行記憶體緩慢增長（對固定短句場景影響不大）
10. **pyproject.toml 作者資訊**：`"Your Name"` 佔位符未更新
11. **`.env.example` 中 TTS 建議與實際不符**：範本建議 `qwen3tts`，但 MEMORY.md 記錄 Edge TTS 才是現用方案

---

## 5. 建議行動方案

### Phase 1：上線最低可行（1-2 天）

1. **Admin 認證**：在 `admin_router.py` 加上 Depends(get_api_key)，與現有認證機制統一
2. **售完狀態持久化**：將 `menu_state_service` 的狀態存到 `menu_state.json`，啟動時讀取
3. **輸入驗證**：user_text 加上 500 字上限、audio file 加上 10MB 上限
4. **Session ID 改為 UUID4**：前端 `crypto.randomUUID()` 替換 `Date.now()`
5. **OrderTicket key 修正**：使用 index 而非 item.name

### Phase 2：穩定化（3-5 天）

6. **LLM 降級策略**：readiness check 失敗時回傳預設訊息（"系統正在啟動，請稍後再試"）
7. **SSE 整合測試**：用 `httpx` AsyncClient 測試 `/api/text-chat` 完整 SSE 流程
8. **app.py 拆分**：checkout + legacy dialogue 端點各自成為獨立 router
9. **刪除舊版端點**：確認無前端依賴後移除 `/dialogue/*` 三個端點
10. **啟動腳本完善**：`start.ps1` 加入 LM Studio 模型檢查 + 依賴服務等待

### Phase 3：品質提升（1-2 週）

11. **VoiceController 重構**：拆為獨立 hooks
12. **LLM caller 重構**：抽出共用的 message 構建 + tool loop 邏輯
13. **監控儀表板**：perf_collector 資料寫入 SQLite，admin 頁面展示延遲趨勢
14. **LoRA 微調完成**：93% -> 97% 目標
15. **壓力測試**：確認單機同時服務 N 個點餐機的上限

---

## 6. 架構整體評價

### 設計模式適當性：良好
系統在地端單機的約束下做出了合理的技術選擇。FastAPI + Next.js + Zustand 的技術棧成熟穩定，SSE 串流架構（ASR -> DM -> 分段 TTS）延遲控制出色。Few-shot priming + Response Template + 幻覺防護的三層策略有效解決了本地 LLM 的可靠性問題。

### 可擴展性：適當
對「單店單機」的定位而言，InMemory session + SQLite + 單 worker 是正確選擇。Redis session store 和 docker-compose 已為未來多機部署預留了擴展路徑。LM Studio 作為 LLM serving 在單機場景足夠，多機場景可切換到 SGLang/vLLM。

### 主要風險
1. **LM Studio 單點故障**：LLM 服務不可用時整個點餐功能癱瘓，無降級方案
2. **Admin 無認證**：目前最大的安全缺口，任何區網內的裝置都能修改菜單/訂單狀態
3. **售完狀態揮發**：後端重啟後售完資訊歸零，營業中可能造成混亂

### 結論
系統核心功能完成度高，LLM pipeline 的工程品質尤其突出。距離生產環境主要差距在安全性（Admin 認證）和可靠度（狀態持久化、降級策略）。按照建議的 Phase 1 行動方案，預估 1-2 天可達到最低可上線標準。
