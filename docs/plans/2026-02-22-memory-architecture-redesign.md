# Memory 架構重構設計

日期：2026-02-22

## 動機

根據 Claude Code 官方 Memory 文件最佳實踐，重構 memory 架構：
- 全域 CLAUDE.md 從 139 行精簡到 ~25 行
- 用 `~/.claude/rules/` 模組化工作流規則
- 用專案 `.claude/rules/` + path-specific 規則
- Auto memory 瘦身，過期狀態由 Obsidian 管理

## 變更摘要

### 全域層級（`~/.claude/`）

| 檔案 | 變更 |
|------|------|
| `CLAUDE.md` | 139→25 行，只留語言/tech/code style/AI 標記 |
| `rules/decision-levels.md` | 新建：P0-P4 決策分層表 |
| `rules/model-delegation.md` | 新建：四層模型分工 + 升級鏈 |
| `rules/obsidian.md` | 新建：Obsidian 操作規則 + @import 詳細規則 |
| `rules/git-workflow.md` | 新建：commit 規範 + 防錯 |
| `rules/skill-management.md` | 新建：Skill 載入策略 |

### 專案層級（`ai-ordering-system/`）

| 檔案 | 變更 |
|------|------|
| `CLAUDE.md` | 13→65 行，從 auto memory 搬入穩定專案知識 |
| `.claude/rules/backend.md` | 新建：Python/FastAPI 規則（path-specific） |
| `.claude/rules/frontend.md` | 新建：Next.js/React 規則（path-specific） |

### Auto Memory

| 檔案 | 變更 |
|------|------|
| `MEMORY.md` | 85→25 行，只保留踩坑紀錄和 insights |

## 原則

- `~/.claude/CLAUDE.md`：精簡核心偏好，每 session 必載
- `~/.claude/rules/*.md`：模組化規則，自動載入，每檔一主題
- 專案 `CLAUDE.md`：穩定專案知識
- 專案 `.claude/rules/`：path-specific 規則，按需載入
- Auto memory：Claude 自己的發現筆記
- Obsidian：唯一的「當前狀態 + 進度」真相來源
