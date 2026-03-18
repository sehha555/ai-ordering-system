# AI 點餐系統 — 生產準備度掃描報告

> 日期：2026-03-08
> 掃描團隊：architect-reviewer / security-auditor / performance-engineer / product-manager
> 範圍：全專案（Backend + Frontend + LLM Pipeline + Admin）

---

## 一、總覽

| 維度 | 評分 | 最高問題 | 說明 |
|------|------|----------|------|
| 架構 | 7/10 | P0 ×1, P1 ×5 | 模組分離清晰、串流設計出色，但併發安全和持久化是硬傷 |
| 安全 | 4/10 | Critical ×1, High ×3 | Admin 完全無認證、Session 可預測、認證形同虛設 |
| 效能 | 7.5/10 | 高 ×1, 中 ×5 | LLM avg 2-3s 可接受，early_tts 機制優秀，但有 blocking I/O 風險 |
| 產品 | 6.5/10 | Blocker ×2 | 語音點餐核心穩健（86% pass rate），但運營閉環缺失 |

**整體結論**：作為早餐店單機地端 AI 點餐系統，核心技術路徑已通，但安全和運營功能是上線前的硬性阻擋。

---

## 二、跨領域共識（4 位專家一致指出）

### 1. ToolRegistry session_id 併發問題（架構 P0 + 安全 Medium）
- 全域單例的 `_session_id` 在多併發請求下會互相覆蓋
- 兩台平板同時點餐就會觸發購物車串擾
- **修復**：per-request 傳遞 session_id，不存在 instance 上

### 2. Admin API 無認證（安全 Critical + 架構 P1 + 產品 Blocker）
- 所有 admin 端點完全開放，任何人可修改菜單、訂單狀態
- **修復**：加入 API Key 或 session-based auth

### 3. InMemory 狀態持久化（架構 P1 + 效能中）
- 菜單售完狀態、session 重啟即遺失
- 多 worker/多機器狀態不一致
- **修復**：Redis 已有程式碼準備（`create_session_store` 工廠），需啟用

### 4. LLM History 無上限（架構 P2 + 效能中）
- 多輪對話 token 超過 n_ctx（16384）會被截斷
- 固定 prompt 已 ~8,562 tokens，剩餘空間有限
- **修復**：滑動窗口限制最大輪數

---

## 三、分領域問題彙整

### A. 架構（16 項）

| 優先級 | 問題 | 工作量 |
|--------|------|--------|
| **P0** | ToolRegistry session_id race condition | 中（需重構 DI） |
| **P1** | 服務容器用 module-level 全域變數 | 中 |
| **P1** | 單 worker 瓶頸（ASR 同步 blocking） | 大 |
| **P1** | SQLite 無連線池、不支援多機 | 中 |
| **P1** | 菜單狀態存 process memory | 小 |
| **P1** | Admin API 無認證 | 小 |
| **P2** | LLM `_post()` 同步 requests + time.sleep | 小 |
| **P2** | 前端 proxy admin 無路由保護 | 小 |
| **P2** | 對話歷史無上限 | 小 |
| **P2** | TTS speak() 建新 event loop | 小 |
| **P2** | 錯誤回應格式不一致 | 中 |
| **P2** | 缺少 graceful shutdown | 中 |
| **P2** | 雙重 Dialogue Manager 架構 | 中（需決策） |
| **P3** | 日誌無集中管理 | 中 |
| **P3** | 缺少 API 版本控制 | 小 |
| **P3** | 缺少 integration/contract test | 大 |

### B. 安全（19 項）

| 嚴重度 | 問題 | 位置 |
|--------|------|------|
| **Critical** | Admin API 無認證 | admin_router.py |
| **High** | Checkout 端點無認證 | app.py:721 |
| **High** | Session ID 無驗證（可預測） | session_store.py |
| **High** | voice_router API Key 驗證形同虛設 | voice_router.py:28 |
| **Medium** | CORS 設定過寬 | app.py:136 |
| **Medium** | 錯誤訊息洩漏內部資訊 | 多處 |
| **Medium** | TTS 路徑穿越風險 | app.py:678 |
| **Medium** | 上傳檔案無大小限制 | voice_router.py:166 |
| **Medium** | 對話紀錄檔名可控 | order_repository.py:140 |
| **Medium** | InMemory Session 無併發保護 | session_store.py:31 |
| **Medium** | ToolRegistry 全域 session_id | tool_registry.py:48 |
| **Medium** | LLM Prompt Injection | llm_tool_caller.py |
| **Medium** | 無 CSRF 保護 | 全部 POST 端點 |
| **Low** | SQL Injection 風險（低，已參數化） | order_repository.py:80 |
| **Low** | 無 Content Security Policy | frontend_next |
| **Low** | ffmpeg 命令注入（已用 list） | app.py:527 |
| **Low** | 依賴版本未鎖定 | pyproject.toml |
| **Low** | 日誌可能記錄 PII | 多處 |
| **Low** | /docs 端點暴露 | FastAPI 預設 |

**OWASP Top 10 狀態**：A01 需改善 / A03 基本通過 / A05 需改善 / A07 需改善 / 其餘通過或低風險

### C. 效能（10 項）

| 影響 | 瓶頸 | 優化建議 | 預期效果 |
|------|------|----------|----------|
| **高** | Legacy `/dialogue/voice` 同步 ASR blocking event loop | 標記棄用或改 async | 防 event loop 凍結 |
| **中** | LLM retry 用 time.sleep blocking thread | 改 asyncio.sleep | 高併發穩定性 |
| **中** | ASR 必須寫 tempfile 到磁碟 | 換 Qwen3-ASR（bytes input） | -50~150ms |
| **中** | TTS cache miss 必須累積全部 chunks | 換本地 TTS（BreezyVoice） | -200~400ms |
| **中** | LLM 同步 requests.post | 改 httpx.AsyncClient | 併發穩定 |
| **中** | 購物車動態內容破壞 prefix cache | 架構限制，監控 | N/A |
| **中** | Session 記憶體無上限 | 限制 history 輪數 | 防記憶體洩漏 |
| **低** | AudioVisualizer 120 頂點每幀 | 降至 80 頂點 | -40% canvas CPU |
| **低** | VAD loop 每幀寫 Zustand | 改 useRef 傳遞 | 降 GC 壓力 |
| **低** | TTS 預熱阻塞啟動 | 分批非同步預熱 | 縮短冷啟動窗口 |

**效能亮點**：early_tts 機制、asyncio.Queue 解耦 DM-TTS、TTS 快取預熱、BallVisualizer 隔離高頻更新

### D. 產品（功能矩陣）

| 功能 | 狀態 | 說明 |
|------|------|------|
| 語音點餐 | 完成 | ASR + LLM + TTS 全鏈路，86% benchmark pass rate |
| 購物車管理 | 完成 | 新增/刪除/修改/查看 |
| 多品項點餐 | 部分 | 簡單混合 OK，10+ 品項失敗（模型限制） |
| 結帳流程 | 完成 | 內用/外帶 + 現金/行動支付 + 取餐號碼 |
| 菜單查詢 | 完成 | query_menu tool |
| 售完管理 | 部分 | 後台 API 有，但 System Prompt 未走統一入口（bug） |
| 後台訂單列表 | 缺失 | 設計完成，待實作（MVP Blocker） |
| 菜單編輯 UI | 部分 | API 有，前端簡陋 |
| 數據分析 | 缺失 | 無訂單統計/客流分析 |
| POS 整合 | 缺失 | 無對接計劃 |
| 電子發票 | 缺失 | 法規要求 |
| 多語言 | 缺失 | 僅中文（台灣） |
| 離線處理 | 缺失 | 完全依賴 LLM + Edge TTS 網路 |

---

## 四、建議優先處理順序

### Phase 0：上線阻擋（1-2 週）
1. **ToolRegistry session_id 修復** — 併發安全是硬性要求
2. **Admin API 認證** — 至少 API Key 保護
3. **Session ID 改 UUID4** — 防預測攻擊
4. **voice_router 認證修復** — 統一認證策略
5. **System Prompt 統一入口 bug** — 售完狀態必須生效
6. **後台訂單列表頁** — 廚房無法看單就無法營運

### Phase 1：生產加固（2-4 週）
7. LLM history 滑動窗口
8. Legacy endpoint blocking ASR 修復
9. LLM retry 改 asyncio.sleep
10. 錯誤回應格式統一
11. 上傳檔案大小限制
12. 檔名 sanitize
13. 菜單狀態持久化（Redis）

### Phase 2：擴展準備（1-2 月）
14. SQLite → PostgreSQL
15. ASR 微服務化
16. Graceful shutdown
17. 結構化日誌 + log aggregator
18. API 版本控制
19. Integration/E2E test

### Phase 3：規模化（長期）
20. 多 worker + 共享模型記憶體
21. 容器編排（K8s）
22. POS 整合
23. 數據分析平台
24. 電子發票

---

## 五、風險提醒

| 風險 | 影響 | 現狀 |
|------|------|------|
| LLM n_ctx 溢出 | 多輪對話後模型截斷或報錯 | 無防護，固定 prompt 已佔 ~8,562/16,384 tokens |
| Edge TTS 斷線 | 語音回覆完全中斷 | 無 fallback，依賴微軟雲端 |
| VAD 靈敏度不穩 | 反覆送「。」空白音訊 | 已知問題，未修 |
| 大冰奶等俗稱 | 模型假裝完成不 call tool | 86% benchmark 中的頑固失敗案例 |

---

*報告由 4 位 AI 專家平行掃描生成，僅供分析參考，不代表實作承諾。*
