# src/config/logging_config.py
"""統一日誌配置 — loguru + 性能計時"""

import logging
import os
import sys
import time
import functools
from contextlib import contextmanager

from loguru import logger
from src.config.settings import settings
from src.config.request_context import get_request_id


# ============================================================================
# 攔截標準 logging（uvicorn / FastAPI / 第三方庫）導入 loguru
# ============================================================================

class _InterceptHandler(logging.Handler):
    """把標準 logging 的訊息轉發到 loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        # 取得對應的 loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到真正的呼叫者
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# ============================================================================
# 性能計時工具
# ============================================================================

_SLOW_THRESHOLD = settings.PERF_SLOW_THRESHOLD


@contextmanager
def PerfTimer(operation: str):
    """Context manager — 記錄程式碼區塊耗時

    用法:
        with PerfTimer("llm_call"):
            result = client.chat(...)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if elapsed >= _SLOW_THRESHOLD:
            logger.warning("[PERF] {} 耗時 {:.3f}s（超過 {}s 閾值）", operation, elapsed, _SLOW_THRESHOLD)
        else:
            logger.info("[PERF] {} 耗時 {:.3f}s", operation, elapsed)


def log_perf(operation: str):
    """Decorator — 自動記錄函數耗時，支援 sync / async

    用法:
        @log_perf("asr_transcribe")
        def transcribe(audio_path): ...
    """
    def decorator(func):
        if asyncio_iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    elapsed = time.perf_counter() - start
                    if elapsed >= _SLOW_THRESHOLD:
                        logger.warning("[PERF] {} 耗時 {:.3f}s（超過 {}s 閾值）", operation, elapsed, _SLOW_THRESHOLD)
                    else:
                        logger.info("[PERF] {} 耗時 {:.3f}s", operation, elapsed)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    elapsed = time.perf_counter() - start
                    if elapsed >= _SLOW_THRESHOLD:
                        logger.warning("[PERF] {} 耗時 {:.3f}s（超過 {}s 閾值）", operation, elapsed, _SLOW_THRESHOLD)
                    else:
                        logger.info("[PERF] {} 耗時 {:.3f}s", operation, elapsed)
            return sync_wrapper
    return decorator


def asyncio_iscoroutinefunction(func):
    """判斷函數是否為 async"""
    import asyncio
    return asyncio.iscoroutinefunction(func)


# ============================================================================
# 初始化
# ============================================================================

def _add_request_id(record: dict) -> None:
    """loguru patcher — 將當前 request_id 注入每筆 log record"""
    record["extra"]["request_id"] = get_request_id()


_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level:<7}</level> | "
    "<cyan>{extra[request_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
    "<level>{message}</level>"
)


def setup_logging():
    """初始化日誌系統 — 應用啟動時呼叫一次"""

    log_level = settings.LOG_LEVEL.upper()
    log_format = settings.LOG_FORMAT

    # prod 環境強制 JSON 日誌
    if settings.is_production and log_format != "json":
        log_format = "json"

    retention_days = settings.LOG_RETENTION_DAYS

    # 移除 loguru 預設 handler
    logger.remove()

    # 注入 request_id patcher
    logger.configure(patcher=_add_request_id)

    # stderr 輸出
    if log_format == "json":
        logger.add(sys.stderr, level=log_level, serialize=True)
    else:
        logger.add(
            sys.stderr,
            level=log_level,
            format=_CONSOLE_FORMAT,
        )

    # 檔案輸出 — 每日輪替，保留天數可配置
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 純文字日誌（含 request_id）
    logger.add(
        os.path.join(log_dir, "app.log"),
        level=log_level,
        rotation="00:00",  # 每日午夜輪替
        retention=f"{retention_days} days",
        encoding="utf-8",
        format=_CONSOLE_FORMAT,
    )

    # JSON 結構化日誌（機器可讀，含 request_id via extra）
    logger.add(
        os.path.join(log_dir, "app.json"),
        level=log_level,
        rotation="1 day",
        retention="7 days",
        encoding="utf-8",
        serialize=True,
    )

    # 攔截標準 logging
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    logger.info("日誌系統已初始化 (level={}, format={}, retention={}天)", log_level, log_format, retention_days)
