# 日誌系統 + 性能監控設計方案

**日期**：2026-02-15
**狀態**：已確認

## 背景

目前後端 70+ 處 `print(stderr)`，無統一日誌框架，無性能監控。

## 決策

- **日誌框架**：loguru
- **性能監控**：輕量級計時（`@log_perf` decorator + `PerfTimer` context manager）
- **輸出格式**：開發彩色 / 生產 JSON（`LOG_FORMAT` 環境變數切換）
- **檔案輸出**：`logs/app.log`，每日輪替，保留 7 天

## 新增檔案

- `src/config/logging_config.py` — loguru 配置 + PerfTimer + @log_perf

## 修改檔案（8 個）

1. `src/api/app.py` — 移除 4 個 debug() 函數，改用 logger；啟動時呼叫 setup_logging()
2. `src/api/voice_router.py` — 移除 debug()，改用 logger；加端對端 PerfTimer
3. `src/services/asr_service.py` — 移除 import logging + print()，統一 loguru；加 @log_perf
4. `src/services/tts_service.py` — 移除 import logging，統一 loguru；加 @log_perf
5. `src/services/llm_tool_caller.py` — 加 logger + PerfTimer
6. `src/services/streaming_orchestrator.py` — 加關鍵流程 logger
7. `src/config/alias_loader.py` — 2 處 print() → logger.warning()
8. `pyproject.toml` — 加 loguru 依賴

## 不動的檔案

- CLI 腳本（voice_ordering_cli.py, run_dm_cli.py）
- 工具測試區塊（tools/*_tool.py 的 __main__）
- 測試腳本（tests/*）

## 環境變數

- `LOG_LEVEL=INFO`（預設）
- `LOG_FORMAT=color`（生產設 json）

## 驗證

1. uvicorn 啟動無報錯
2. 前端測試通過
3. GET /healthz 日誌正常輸出
4. logs/app.log 有寫入
5. pytest 無 regression
