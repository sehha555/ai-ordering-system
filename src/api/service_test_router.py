# src/api/service_test_router.py
"""服務狀態測試 + TTS 直接操作 Router"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.requests import Request

from src.api.auth import get_api_key
from src.api.rate_limit import limiter
from src.config.settings import settings
from src.services import container

router = APIRouter(tags=["service-test"])


@router.get("/llm/test")
@limiter.limit(settings.RATE_LIMIT_TEST)
async def test_llm(request: Request, api_key: str = Depends(get_api_key)):
    """測試 LLM 服務狀態"""
    try:
        import requests
        resp = requests.get("http://127.0.0.1:1234/v1/models", timeout=5)
        models = resp.json().get("data", [])
        return {
            "service": "LLM (LM Studio)",
            "status": "ready",
            "model": container.llm_caller.model,
            "available_models": [m.get("id") for m in models],
        }
    except Exception as e:
        return {
            "service": "LLM (LM Studio)",
            "status": "error",
            "error": str(e),
        }


@router.get("/asr/test")
@limiter.limit(settings.RATE_LIMIT_TEST)
async def test_asr(request: Request, api_key: str = Depends(get_api_key)):
    """測試 ASR 服務狀態"""
    return {
        "service": f"ASR ({container.asr_service.__class__.__name__})",
        "status": "ready" if container.asr_service.model else "not_loaded",
        "model": getattr(container.asr_service, "model_name", "unknown"),
        "language": "zh"
    }


@router.get("/tts/test")
@limiter.limit(settings.RATE_LIMIT_TEST)
async def test_tts(request: Request, api_key: str = Depends(get_api_key)):
    """測試 TTS 服務狀態"""
    return {
        "service": "TTS (Edge TTS)",
        "status": "ready" if container.tts_service.engine else "not_loaded",
        "properties": container.tts_service.get_properties()
    }


@router.post("/tts/speak")
@limiter.limit(settings.RATE_LIMIT_TEST)
async def tts_speak(
    request: Request,
    text: str,
    api_key: str = Depends(get_api_key)
):
    """直接調用 TTS 將文字轉為語音"""
    result = container.tts_service.speak(text)
    return result


@router.get("/tts/play")
@limiter.limit(settings.RATE_LIMIT_TEST)
async def tts_play(
    request: Request,
    path: str,
    api_key: str = Depends(get_api_key)
):
    """播放 TTS 生成的音訊檔案"""
    import tempfile
    # 安全檢查：只允許播放 TTS 輸出目錄的檔案
    tts_dir = os.path.realpath(os.path.join(tempfile.gettempdir(), "tts_output"))

    # 解析真實路徑（防 symlink traversal），Windows 大小寫不敏感比較
    real_path = os.path.realpath(path)

    if not real_path.lower().startswith(tts_dir.lower()):
        raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        real_path,
        media_type="audio/mpeg",
        filename="response.mp3"
    )
