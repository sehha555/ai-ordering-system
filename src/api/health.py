# src/api/health.py
"""健康檢查路由 — liveness (/healthz) + readiness (/readyz)"""

import os

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.config.settings import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness():
    """Liveness probe — 零依賴，只要 process 活著就回 200"""
    return {"ok": True}


@router.get("/readyz")
async def readiness():
    """Readiness probe — 檢查各元件是否就緒"""
    checks = {}
    all_ok = True

    # 1. SQLite DB 可讀寫
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "orders.db")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    db_writable = os.access(db_dir, os.W_OK)
    checks["sqlite"] = "ok" if db_writable else "not_writable"
    if not db_writable:
        all_ok = False

    # 2. Session Store 狀態（透過 ping() 公開方法）
    try:
        from src.api.app import _session_store
        store_type = type(_session_store).__name__
        checks["session_store"] = {"type": store_type, "status": "ok"}

        if hasattr(_session_store, "ping"):
            try:
                ok = _session_store.ping()
                checks["session_store"]["ping"] = "ok" if ok else "failed"
                if not ok:
                    all_ok = False
            except Exception:
                checks["session_store"]["ping"] = "failed"
                all_ok = False
    except Exception as e:
        checks["session_store"] = {"status": "error", "detail": str(e)}
        all_ok = False

    # 3. LLM 服務可達（async 非阻塞）
    try:
        llm_base = settings.LLM_BASE_URL.rsplit("/chat/completions", 1)[0]
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{llm_base}/models", timeout=3)
        checks["llm"] = "ok" if resp.status_code == 200 else f"status_{resp.status_code}"
        if resp.status_code != 200:
            all_ok = False
    except Exception as e:
        checks["llm"] = f"unreachable: {type(e).__name__}"
        all_ok = False

    # 4. ASR 模型已載入
    try:
        from src.api.app import _asr_service
        asr_loaded = bool(getattr(_asr_service, "model", None))
        checks["asr"] = "ok" if asr_loaded else "not_loaded"
        if not asr_loaded:
            all_ok = False
    except Exception as e:
        checks["asr"] = f"error: {type(e).__name__}"
        all_ok = False

    return JSONResponse(
        content={"ready": all_ok, "checks": checks},
        status_code=200 if all_ok else 503,
    )
