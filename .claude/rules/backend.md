---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
---

# Backend 開發規則

- Framework: FastAPI + Pydantic v2
- 測試：`pytest tests/ -x -q`（快速跑全部）
- 依賴管理：`uv sync --extra models --extra dev`
- ASR/TTS/LLM 切換統一透過 `src/config/models.py` 的 enum
- 新增 API endpoint 必須在 `tests/` 有對應測試
