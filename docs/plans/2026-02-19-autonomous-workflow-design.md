# 自動化循環工作流設計

> 日期：2026-02-19
> 狀態：已確認，寫入 `~/.claude/CLAUDE.md`

## 目標

將 Claude Code 工作流從手動逐步確認（~50% 自動）升級為 95% 自動循環，人類只負責：
1. 每日開工確認計劃（P1）
2. P0 級決策（架構/部署/不可逆）
3. 瀏覽通知（P2 commit/任務完成）

## 決策分層 P0-P4

| 等級 | 決策權 | 行為 | 範例 |
|------|--------|------|------|
| P0 | 🔴 人類決定 | 阻塞等待 | 架構決策、部署變更、不可逆操作、升級鏈用盡 |
| P1 | 🟡 AI 事前報告 | 展示計劃等確認 | 每日工作規劃 |
| P2 | 🟢 AI 事後通知 | 一句話通知 | commit、push、任務完成、依賴變更 |
| P3 | ⚪ AI 寫日誌 | 寫入 Obsidian | 開發、修復、測試、筆記更新 |
| P4 | ⬛ AI 靜默 | 不顯示 | 探索、分工、subagent、skill 載入 |

### P0 判斷標準
- 新模組 / 微服務 / 技術選型
- Dockerfile / CI / 環境變數 schema 修改
- 刪檔案 / 刪分支 / DROP TABLE
- 單一 commit 變更 >10 檔案
- 模型升級鏈用盡仍失敗

## 循環工作流

```
Session Start
  → Phase 0: 環境感知 (P4 靜默)
  → Phase 1: 今日計劃 (P1 等確認) ← 唯一等待點

  → Task Loop (自動循環):
      Step 1: 取任務 (P4)
      Step 2: Skill 檢查 + 建 Obsidian 筆記 (P4+P3 平行)
      Step 3: 規劃 + 執行 (P3, subagent 平行)
      Step 4: 品質門檻 — 測試 + lint + type check (P3)
      Step 5: Commit + Push (P2 通知)
      Step 6: 更新 Obsidian 紀錄 (P3 平行)
      Step 7: → 回到 Step 1

  → Session End: 總結 + 交接摘要 (P2 通知)
```

## 模型自動升級鏈

```
Haiku → (失敗 ×3) → Sonnet → (失敗 ×3) → Opus subagent → (失敗) → P0 問人
```

升級時整理：已嘗試方法、失敗原因、錯誤訊息 → 傳給下一個 agent。

## Skill 管理

- Session 開始：預載相關 skill
- 每個任務：比對關鍵字載入
- 新領域：find-skills 搜尋 → 安裝 → 記錄到 auto-skill

## Commit 策略

- 1 任務 = 1 commit
- >5 檔案拆子 commit
- 品質門檻：測試 + lint + type check 通過
- 不混 type

## 任務排序

- AI 自主判斷，依賴關係優先
- 外部卡住的任務自動跳過
- P1 計劃時展示排序邏輯

## Obsidian 整合

- 建立/更新筆記：Gemini subagent 平行處理
- 維持現有結構：日期節點 → 任務 01, 02...→ 執行紀錄
- 任務完成後自動更新：待辦_當前.md + 專案整體進度.md
- Session 結束：寫交接摘要

## Session 交接

每個 session 結束前寫入 Obsidian：
- 今日完成清單
- 未完成/跳過的任務 + 原因
- 下次建議做什麼
- 當前 branch 狀態 + 最新 commit

## 與舊版差異

| 項目 | 舊版 | 新版 |
|------|------|------|
| 計劃確認 | 每個任務都等 | 只有每日 P1 等一次 |
| Commit | 每次展示 diff 等確認 | 自動 commit (P2 通知) |
| Push | 需要明確指令 | CI 通過後自動 push (P2 通知) |
| Obsidian | 手動觸發 | Gemini 平行自動處理 |
| 模型選擇 | 人工判斷 | 自動選擇 + 失敗自動升級 |
| Skill | 手動載入 | 混合：預載 + 按需 + 自動探索 |
| 任務排序 | 人工排序 | AI 判斷 + P1 確認 |
