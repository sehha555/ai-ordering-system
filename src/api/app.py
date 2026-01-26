import os
import re
from fastapi import FastAPI, HTTPException, Security, Depends, File, UploadFile
from fastapi.security.api_key import APIKeyHeader
from typing import List, Optional
from pydantic import BaseModel
from src.repository.order_repository import order_repo
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.services.asr_service import ASRService
from src.services.tts_service import TTSService

app = FastAPI(title="Yuan Rice Ball Order API")

# 初始化服務
_session_store = InMemorySessionStore()
_dialogue_manager = DialogueManager(store=_session_store)
_asr_service = ASRService(model_size="base", language="zh")
_tts_service = TTSService(language="zh", rate=150)


class TextDialogueRequest(BaseModel):
    """文本對話請求"""
    session_id: str
    text: str


class TextDialogueResponse(BaseModel):
    """文本對話響應"""
    session_id: str
    response: str
    status: str = "ok"

API_KEY = os.getenv("API_KEY", "yuan-secret-key")
api_key_header = APIKeyHeader(name="X-API-Key")

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key

def validate_order_id(order_id: str):
    if not re.match(r"^[A-Z0-9-]+$", order_id) or len(order_id) > 20:
        raise HTTPException(status_code=400, detail="Invalid Order ID format")

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/orders/{order_id}")
async def get_order(order_id: str, api_key: str = Depends(get_api_key)):
    validate_order_id(order_id)
    order = order_repo.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/orders")
async def list_orders(
    date: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    api_key: str = Depends(get_api_key)
):
    orders = order_repo.list_orders(date=date, status=status, limit=limit, offset=offset)
    return {"items": orders, "count": len(orders)}


# ============================================================================
# 語音對話 API 端點（新增）
# ============================================================================

@app.post("/dialogue/text", response_model=TextDialogueResponse)
async def text_dialogue(request: TextDialogueRequest, api_key: str = Depends(get_api_key)):
    """
    文本對話端點（文字輸入，文字輸出）

    用例：
        curl -X POST http://localhost:8000/dialogue/text \
          -H "X-API-Key: yuan-secret-key" \
          -H "Content-Type: application/json" \
          -d '{"session_id": "user123", "text": "我要飯糰"}'
    """
    try:
        # 調用對話管理器
        response = _dialogue_manager.handle(request.session_id, request.text)

        return TextDialogueResponse(
            session_id=request.session_id,
            response=response,
            status="ok"
        )
    except Exception as e:
        return TextDialogueResponse(
            session_id=request.session_id,
            response=f"錯誤: {str(e)}",
            status="error"
        )


@app.post("/dialogue/voice")
async def voice_dialogue(
    session_id: str,
    audio_file: UploadFile = File(...),
    api_key: str = Depends(get_api_key)
):
    """
    語音對話端點（語音輸入，語音輸出）

    用例：
        curl -X POST http://localhost:8000/dialogue/voice \
          -H "X-API-Key: yuan-secret-key" \
          -F "session_id=user123" \
          -F "audio_file=@speech.wav"
    """
    try:
        import tempfile

        # 保存上傳的音訊文件到臨時位置
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            content = await audio_file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # 使用 ASR 將語音轉為文字
            asr_result = _asr_service.transcribe(tmp_path)

            if asr_result.get("error"):
                return {
                    "session_id": session_id,
                    "status": "error",
                    "asr_error": asr_result.get("error"),
                    "response": None,
                    "audio_url": None
                }

            user_text = asr_result.get("text", "")

            if not user_text:
                return {
                    "session_id": session_id,
                    "status": "error",
                    "error": "無法識別語音內容",
                    "response": None,
                    "audio_url": None
                }

            # 調用對話管理器
            dialogue_response = _dialogue_manager.handle(session_id, user_text)

            # 使用 TTS 將回應轉為語音
            tts_result = _tts_service.speak(dialogue_response)

            return {
                "session_id": session_id,
                "status": "ok",
                "user_text": user_text,
                "response": dialogue_response,
                "audio_url": tts_result.get("file_path")
            }

        finally:
            # 清理臨時文件
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        return {
            "session_id": session_id,
            "status": "error",
            "error": str(e),
            "response": None,
            "audio_url": None
        }


@app.get("/asr/test")
async def test_asr(api_key: str = Depends(get_api_key)):
    """
    測試 ASR 服務狀態
    """
    return {
        "service": "ASR (Whisper)",
        "status": "ready" if _asr_service.model else "not_loaded",
        "model": "base",
        "language": "zh"
    }


@app.get("/tts/test")
async def test_tts(api_key: str = Depends(get_api_key)):
    """
    測試 TTS 服務狀態
    """
    return {
        "service": "TTS (pyttsx3)",
        "status": "ready" if _tts_service.engine else "not_loaded",
        "properties": _tts_service.get_properties() if _tts_service.engine else {}
    }


@app.post("/tts/speak")
async def tts_speak(
    text: str,
    api_key: str = Depends(get_api_key)
):
    """
    直接調用 TTS 將文字轉為語音

    用例：
        curl -X POST http://localhost:8000/tts/speak \
          -H "X-API-Key: yuan-secret-key" \
          -d "text=歡迎光臨" \
          -G
    """
    result = _tts_service.speak(text)
    return result
