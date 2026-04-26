# AI Ordering System

<!-- 對應 AI-OS/Projects/ 下的資料夾名稱；session skill 用這個找交接筆記/執行計劃 -->
project: ordering-system

## Architecture
- **Backend**: FastAPI (port 8000) — ASR/TTS/LLM pipeline
- **Frontend (Next.js)**: `src/frontend_next/` — port 3000, App Router
- **Frontend (legacy)**: `src/frontend/` — Vanilla JS, served by FastAPI
- Next.js rewrites: `/api/*`, `/healthz`, `/cart/*`, `/static/*` → backend
- SSE streaming: `/api/voice-chat`

## Tech Stack
- Next.js 16 + React 19 + Tailwind v4 + Zustand 5 + Framer Motion 12
- ASR: SenseVoice-Small（ModelScope hub, GPU）
- LLM: Qwen3.5-9B（LM Studio，ud-q4_k_xl 量化）
- TTS: Edge TTS（`zh-TW-HsiaoChenNeural`）
- VAD: 自適應閾值 + silence timeout 1500ms + 最大錄音 30s

## Python 環境
- uv 管理，`.python-version` 鎖 3.11（CUDA）
- `uv sync --extra models --extra dev`

## Key Files
**Backend**: `app.py`（FastAPI）/ `voice_router.py`（SSE）/ `models.py`（ASR/TTS 切換）/ `dialogue_manager.py`（狀態機）/ `streaming_orchestrator.py`（串流）/ `tool_registry.py`（Function Calling）
**Frontend**: `VoiceController.tsx`（VAD+SSE）/ `AudioVisualizer.tsx`（波形）/ `useStore.ts`（Zustand）
**ASR 後處理**: `asr_postprocess.py` — opencc s2twp + 領域詞彙修正表

## Brand Colors
Primary: `#729DAD` / Light: `#8fb3c0` / Dark: `#5a8494`
BG: `#f4f7f8` / Success: `#4a9d68` / Error: `#c45c5c` / Warning: `#c49a30`

## 情境指引
- 啟動/測試/lint/benchmark 指令 → 先看 `README.md`
- 設計文件 → `docs/plans/`

## Benchmark 護欄
- 跑之前先確認 LM Studio 模型已載入，詳細規則 → `memory/lm-studio.md`

## Agent Team（實驗性）
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- 同一檔案不能兩人同時改
- 介面變更必須通知相關隊友
- 隊友間要讓他們互相討論、協作

## Codex會審查你寫過的代碼