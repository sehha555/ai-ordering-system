# Agent Team Dashboard — Phase 1 設計

日期：2026-02-25
狀態：approved

## 目標

建立跨專案通用的 Agent Team Dashboard，以網頁即時監控 Claude Code agent team 的任務進度和成員狀態。

## 需求

### Phase 1（本次實作）
- Task 進度面板：即時顯示每個 task 的狀態、owner、阻塞關係
- Agent 狀態面板：顯示每個 agent 的工作狀態（working/idle/done）
- Stats 面板：完成率、進度條
- Team 選擇器：切換不同 team
- SSE 即時更新：檔案變更自動推送

### Phase 2（後續）
- Chat 討論面板：監聽 team-chat.jsonl
- Summary 總結面板：對話摘要與關鍵決策

## 技術棧

- Next.js 16 (App Router) + React 19 + TypeScript
- Tailwind CSS v4（深色主題）
- Zustand 5（狀態管理）
- chokidar（檔案監聽）
- SSE（即時推送）

## 安裝位置

```
~/.claude/tools/dashboard/
```

跨專案通用，任何 session 都能啟動。Port 3100（避免與專案 3000 衝突）。

## 架構

```
~/.claude/tools/dashboard/
├── package.json
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── app/
│   ├── layout.tsx                  # 全局佈局 + 深色主題
│   ├── page.tsx                    # Bento Grid 主頁
│   ├── globals.css                 # Tailwind + 自訂變數
│   ├── api/
│   │   ├── teams/route.ts          # GET 所有 teams
│   │   ├── tasks/[teamId]/route.ts # GET 該 team 的 tasks
│   │   └── sse/route.ts            # SSE 推送檔案變更
│   └── components/
│       ├── TaskPanel.tsx           # 任務清單 + 狀態 badge
│       ├── AgentPanel.tsx          # Agent 卡片 + 狀態燈號
│       ├── StatsPanel.tsx          # 完成率 + 進度條
│       └── TeamSelector.tsx        # 切換不同 team
├── lib/
│   ├── watcher.ts                  # chokidar 監聽 ~/.claude/tasks/ + teams/
│   ├── parser.ts                   # 解析 task JSON + team config
│   └── types.ts                    # TypeScript 型別定義
└── store/
    └── useDashboardStore.ts        # Zustand store
```

## 資料模型

```typescript
// ~/.claude/tasks/{teamId}/{id}.json
interface Task {
  id: string
  subject: string
  description: string
  activeForm?: string
  status: 'pending' | 'in_progress' | 'completed'
  owner?: string
  blocks: string[]
  blockedBy: string[]
}

// ~/.claude/teams/{name}/config.json → members[]
interface Agent {
  name: string
  agentType: string
  status: 'working' | 'idle' | 'done'  // 從 task ownership 推導
  currentTask?: string
  completedCount: number
}

interface Team {
  name: string
  members: Agent[]
  tasks: Task[]
}
```

### Agent 狀態推導規則

| 條件 | 狀態 |
|------|------|
| 有 in_progress task 且 owner 是自己 | working |
| 有 task 但全是 pending | idle |
| 所有 owned task 都 completed | done |
| 沒有任何 task assigned | idle |

## API Routes

| 路由 | 方法 | 說明 |
|------|------|------|
| `/api/teams` | GET | 掃描 ~/.claude/teams/ 列出所有 team |
| `/api/tasks/[teamId]` | GET | 讀取該 team 所有 task JSON |
| `/api/sse` | GET | SSE stream，推送 task/team 檔案變更 |

### SSE 事件格式

```
event: task_update
data: {"teamId": "xxx", "task": {...}}

event: team_update
data: {"teamId": "xxx", "members": [...]}
```

## UI 設計

### 佈局：Bento Grid

```
+------------------+---------------------------+
|  Tasks           |  Agents                   |
|  (tall card)     |  [status] lead  [Task 2]  |
|                  |  [status] writer [idle]   |
|  [ ] Task 1     +---------------------------+
|  [~] Task 2     |  Stats                    |
|  [v] Task 3     |  Completed: 3/7    43%    |
|                  |  [============----] bar   |
+------------------+--------------+------------+
|  Discussion (Phase 2)          | Summary     |
|  [placeholder]                 | (Phase 2)   |
+---------------------------------+------------+
```

### 設計規範
- 深色主題（系統風格）
- 無 emoji，純文字 + 圖示
- 狀態燈號用色點（綠/黃/灰）
- 卡片圓角 + 微邊框
- 字型：系統 monospace

## Skill 定義

檔案：`~/.claude/skills/dashboard.md`

觸發指令：`/dashboard`

行為：
1. 檢查 `~/.claude/tools/dashboard/` 是否已安裝
2. 未安裝 → 提示使用者安裝
3. 已安裝 → 背景啟動 `npm run dev --prefix ~/.claude/tools/dashboard -- -p 3100`
4. 等 server ready → 開啟瀏覽器 `http://localhost:3100`

## 實作計畫

### Task 1：專案初始化
- `npm create next-app` at `~/.claude/tools/dashboard/`
- 設定 Tailwind v4 深色主題
- 基礎 layout.tsx + page.tsx

### Task 2：資料層
- lib/types.ts — 型別定義
- lib/parser.ts — 解析 task JSON + team config
- lib/watcher.ts — chokidar 監聽

### Task 3：API Routes
- /api/teams — 列出 teams
- /api/tasks/[teamId] — 列出 tasks
- /api/sse — SSE 即時推送

### Task 4：前端元件
- TeamSelector.tsx
- TaskPanel.tsx
- AgentPanel.tsx
- StatsPanel.tsx
- store/useDashboardStore.ts

### Task 5：Bento Grid 佈局 + 深色主題
- page.tsx 組裝所有面板
- globals.css 深色主題變數
- 響應式斷點

### Task 6：Skill 檔案
- ~/.claude/skills/dashboard.md

### Task 7：測試 + 驗證
- 用現有的 ~/.claude/tasks/ 資料驗證
- 確認 SSE 即時更新正常
