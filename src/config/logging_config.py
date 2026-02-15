# src/config/logging_config.py
"""統一日誌配置 — loguru + 性能計時"""

import logging
import os
import sys
import time
import functools
from contextlib import contextmanager

from loguru import logger


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

_SLOW_THRESHOLD = float(os.getenv("PERF_SLOW_THRESHOLD", "5.0"))


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

def setup_logging():
    """初始化日誌系統 — 應用啟動時呼叫一次"""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "color")  # "color" | "json"

    # 移除 loguru 預設 handler
    logger.remove()

    # stderr 輸出
    if log_format == "json":
        logger.add(sys.stderr, level=log_level, serialize=True)
    else:
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>",
        )

    # 檔案輸出 — 每日輪替，保留 7 天
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger.add(
        os.path.join(log_dir, "app.log"),
        level=log_level,
        rotation="00:00",  # 每日午夜輪替
        retention="7 days",
        encoding="utf-8",
        serialize=(log_format == "json"),
    )

    # 攔截標準 logging
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    logger.info("日誌系統已初始化 (level={}, format={})", log_level, log_format)
