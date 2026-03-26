import asyncio
import os
import re
import json
import uuid
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from src.config.logging_config import setup_logging
from src.config.request_context import request_id_var
from src.config.settings import settings
from src.repository.order_repository import order_repo
from src.utils.db_backup import backup_database
from src.utils.perf_collector import perf_collector
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import create_session_store
from src.dm.system_prompts import SystemPromptBuilder
from src.services.asr_service import create_asr_service
from src.config.models import ASR_BACKEND
from src.services.tts_service import TTSService
from src.services.llm_tool_caller import LLMToolCaller
from src.dm.tool_registry import ToolRegistry
from src.api.rate_limit import limiter

# 初始化日誌系統
setup_logging()

# 啟動時自動備份資料庫
backup_database()

# ============================================================================
# 載入店家設定
# ============================================================================


def load_store_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "store_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


from src.api.voice_router import router as voice_router  # noqa: E402
from src.api.health import router as health_router  # noqa: E402
from src.api.admin_router import router as admin_router  # noqa: E402
from src.api.checkout_router import router as checkout_router  # noqa: E402
from src.api.service_test_router import router as service_test_router  # noqa: E402
from src.config.menu_constants import build_menu_categories  # noqa: E402

from contextlib import asynccontextmanager  # noqa: E402


def _validate_startup():
    """啟動驗證 — 檢查必要條件"""
    # SQLite DB 可讀寫
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "orders.db")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if not os.access(db_dir, os.W_OK):
        logger.warning("[STARTUP] orders.db 目錄不可寫: {}", db_dir)

    # prod 環境 API_KEY 必須設定
    if settings.is_production and not settings.API_KEY:
        raise RuntimeError("ENVIRONMENT=prod 時必須設定 API_KEY")

    # prod 環境建議 JSON 日誌
    if settings.is_production and settings.LOG_FORMAT != "json":
        logger.warning("[STARTUP] 生產環境建議設定 LOG_FORMAT=json")

    logger.info(
        "[STARTUP] 環境={}, CORS={}, Session TTL={}min",
        settings.ENVIRONMENT,
        settings.cors_origin_list,
        settings.SESSION_TTL_MINUTES,
    )


@asynccontextmanager
async def lifespan(app):
    # startup: 載入店家設定（移出模組層級，避免 import 時 JSON 不存在 crash）
    try:
        app.state.store_config = load_store_config()
    except FileNotFoundError as e:
        logger.error(
            "[STARTUP] 找不到 store_config.json，請確認 src/config/store_config.json 存在: {}", e
        )
        raise
    except Exception as e:
        logger.error("[STARTUP] 載入 store_config.json 失敗: {}", e)
        raise

    # startup: 啟動驗證
    _validate_startup()

    # startup: 背景預熱 TTS 快取
    from src.services.tts_cache import tts_cache
    from src.services.tts_implementations import create_tts_model as _create_tts
    from src.config.models import TTS_BACKEND as _tts_backend

    _warmup_tts = _create_tts(_tts_backend)
    asyncio.create_task(tts_cache.warmup(_warmup_tts))

    # startup: LLM KV cache 預熱（送完整 system prompt + priming + tools，讓 LM Studio cache 住固定前綴）
    async def _warmup_llm():
        try:
            logger.info("[STARTUP] LLM KV cache 預熱開始...")
            from src.dm.tool_priming import get_priming_messages

            system_prompt = SystemPromptBuilder().build()
            priming = get_priming_messages()
            tools_schema = _tool_registry.get_tools_schema()
            messages = [
                {"role": "system", "content": system_prompt},
                *priming,
                {"role": "user", "content": "你好"},
            ]
            await _llm_caller.ping(messages=messages, tools_schema=tools_schema)
            logger.info("[STARTUP] LLM KV cache 預熱完成")
        except Exception as e:
            logger.warning("[STARTUP] LLM warmup 失敗（不影響啟動）: {}", e)

    asyncio.create_task(_warmup_llm())

    # startup: Session 背景清理任務（每 5 分鐘）
    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    yield

    # shutdown: 取消背景任務
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Yuan Rice Ball Order API", lifespan=lifespan)

# 全域限流器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - 從設定檔讀取允許的來源
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """為每個 HTTP 請求生成短 UUID，存入 ContextVar 供日誌追蹤"""

    async def dispatch(self, request, call_next):
        rid = str(uuid.uuid4())[:8]
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


app.add_middleware(RequestIdMiddleware)

_STARTUP_BYPASS = frozenset({"/healthz", "/readyz", "/docs", "/openapi.json"})


@app.middleware("http")
async def startup_guard(request: Request, call_next):
    """startup 完成前，非 health 端點回 503"""
    from src.services import container as _ctr

    if _ctr.session_store is None and request.url.path not in _STARTUP_BYPASS:
        from starlette.responses import JSONResponse

        return JSONResponse(status_code=503, content={"detail": "伺服器啟動中，請稍候"})
    return await call_next(request)


# 註冊路由
app.include_router(health_router)
app.include_router(voice_router, prefix="/api", tags=["voice"])
app.include_router(admin_router)
app.include_router(checkout_router)
app.include_router(service_test_router)

# 掛載靜態檔案（如果目錄存在）
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")

# 初始化服務
_session_store = create_session_store(
    redis_url=settings.REDIS_URL,
    ttl_minutes=settings.SESSION_TTL_MINUTES,
)


async def _session_cleanup_loop():
    """背景任務：定期清理過期 session"""
    while True:
        await asyncio.sleep(300)  # 每 5 分鐘
        try:
            cleaned = _session_store.cleanup()
            if cleaned:
                logger.info("背景清理 {} 個過期 session", cleaned)
        except Exception as e:
            logger.error("Session 清理失敗: {}", e)


_llm_caller = LLMToolCaller(
    base_url=settings.LLM_BASE_URL,
    model=settings.LLM_MODEL,
    timeout=settings.LLM_TIMEOUT,
)
_dialogue_manager = DialogueManager(llm=_llm_caller, store=_session_store)
_tool_registry = ToolRegistry(_dialogue_manager, _session_store)
_asr_service = create_asr_service(ASR_BACKEND, language="zh")
_tts_service = TTSService(voice="female", rate="+0%")

# 同步到服務容器，供其他模組使用（消除循環依賴）
from src.services import container as _container  # noqa: E402

_container.session_store = _session_store
_container.llm_caller = _llm_caller
_container.tool_registry = _tool_registry
_container.asr_service = _asr_service
_container.tts_service = _tts_service

from src.api.auth import get_api_key  # noqa: E402


def validate_order_id(order_id: str):
    if not re.match(r"^[A-Z0-9-]+$", order_id) or len(order_id) > 20:
        raise HTTPException(status_code=400, detail="Invalid Order ID format")


@app.get("/")
async def serve_frontend():
    """根路徑返回前端頁面"""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(frontend_path):
        return FileResponse(frontend_path)
    return {"message": "Voice Dashboard API", "docs": "/docs"}


@app.get("/api/perf-stats")
async def get_perf_stats(api_key: str = Depends(get_api_key)):
    """
    回傳最近 50 筆語音請求各階段耗時統計
    欄位：asr_s, dm_s, ttfa_s（首個音訊）, tts_s, total_s
    重啟後清零（in-memory）
    """
    return perf_collector.get_stats()


@app.get("/api/perf-history")
def get_perf_history(hours: float = 24, limit: int = 500, api_key: str = Depends(get_api_key)):
    """從 SQLite 查詢歷史效能紀錄（同步 def，FastAPI 自動在 threadpool 執行）"""
    return {"entries": perf_collector.query_history(hours=hours, limit=limit)}


# ============================================================================
# 店家設定 API
# ============================================================================


@app.get("/api/store-config")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def get_store_config(request: Request):
    """取得店家設定（前端用）"""
    store_config = request.app.state.store_config
    return {"store": store_config["store"], "ui": store_config["ui"]}


# ============================================================================
# 菜單 API
# ============================================================================


@app.get("/api/menu")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def get_menu(request: Request):
    """
    取得完整菜單供前端渲染
    按分類組織，包含圖示
    """
    return {"categories": build_menu_categories()}


@app.get("/orders/{order_id}")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def get_order(request: Request, order_id: str, api_key: str = Depends(get_api_key)):
    validate_order_id(order_id)
    order = order_repo.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@app.get("/orders")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def list_orders(
    request: Request,
    date: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    api_key: str = Depends(get_api_key),
):
    orders = order_repo.list_orders(date=date, status=status, limit=limit, offset=offset)
    return {"items": orders, "count": len(orders)}
