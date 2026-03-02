# 源飯糰 AI 語音點餐系統

AI 語音點餐系統原型 — FastAPI 後端 + Next.js 前端。

## 安裝

```bash
# Python 依賴（uv 管理，.python-version 鎖 3.11）
uv sync --extra models --extra dev

# 前端依賴
cd src/frontend_next && pnpm install
```

## 啟動

```bash
# 後端（port 8000，不加 --reload，symlink 會導致 StatReload crash）
uv run python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000

# 前端（port 3000）
cd src/frontend_next && pnpm dev

# 手機測試：http://192.168.0.46:3000
```

## 測試

```bash
# 後端全部測試
uv run python -m pytest tests/ -x -q

# 指定測試檔
uv run python -m pytest tests/test_xxx.py -x -v

# 前端測試
cd src/frontend_next && pnpm test

# BDD / 安全 / 契約測試
uv run pytest -m bdd
uv run pytest -m security
uv run pytest -m contract
```

## Lint / Type Check

```bash
# Ruff lint（commit 前必跑）
uv run ruff check src/

# Ruff 自動修復（F401/F541/W292 可自動修，F841/E402/E701 需手動）
uv run ruff check src/ --fix

# MyPy
uv run mypy src/
```

## Benchmark

```bash
# LLM benchmark（需要 LM Studio 在跑）
PYTHONIOENCODING=utf-8 uv run python -m benchmarks.run_benchmark --type llm

# ASR / TTS / 全部
uv run python -m benchmarks.run_benchmark --type asr|tts|e2e|all

# 指定模型
uv run python -m benchmarks.run_benchmark --type llm --model qwen3-30b-a3b
```

## 專案結構

```
src/
├── api/           # FastAPI（app.py, voice_router.py, admin_router.py）
├── dm/            # 對話管理（dialogue_manager.py, tool_registry.py, system_prompts.py）
├── services/      # ASR/TTS/LLM 服務（streaming_orchestrator.py）
├── config/        # 模型設定（models.py）
├── repository/    # 資料層（order_repository.py）
├── frontend/      # Legacy vanilla JS
└── frontend_next/ # Next.js App Router（主力前端）
    ├── app/       # 頁面（page.tsx, admin/）
    ├── components/# UI 元件（VoiceController, AudioVisualizer）
    └── store/     # Zustand（useStore.ts）
benchmarks/        # 模型 benchmark（run_benchmark.py, config.yaml）
tests/             # pytest 測試
docs/plans/        # 設計文件
```
