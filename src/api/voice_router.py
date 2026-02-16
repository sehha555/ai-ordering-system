# src/api/voice_router.py
from fastapi import APIRouter, UploadFile, File, Depends, Form
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
import json
import os
from loguru import logger

from src.services.streaming_orchestrator import StreamingOrchestrator

router = APIRouter()

# API Key 驗證
API_KEY = os.getenv("API_KEY", "yuan-secret-key")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key_optional(api_key: str = Depends(api_key_header)):
    """可選的 API Key 驗證（用於開發測試）"""
    return api_key


async def event_generator(orchestrator: StreamingOrchestrator, audio_bytes: bytes, session_id: str):
    """將 orchestrator 事件轉換為 SSE 格式"""
    async for event in orchestrator.process_audio_stream(audio_bytes, session_id=session_id):
        # Format as SSE
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"


@router.post("/voice-chat")
async def voice_chat(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    api_key: str = Depends(get_api_key_optional)
):
    """
    語音對話 SSE 端點

    接收音訊檔案 + session_id，返回 Server-Sent Events 串流：
    - event: thinking     - 開始處理
    - event: transcription - ASR 轉錄結果
    - event: cart_update  - 購物車更新
    - event: audio_chunk  - TTS 音訊片段 (base64)
    """
    logger.info("[VOICE] 收到語音請求: session_id={}", session_id)
    audio_bytes = await file.read()

    # 取得服務實例（從 app.py 導入）
    # 這裡使用延遲導入避免循環依賴
    from src.api.app import _asr_service, _dialogue_manager, _tts_service, _session_store, _llm_caller, _tool_registry, SYSTEM_PROMPT
    from src.services.tts_implementations import EdgeTTSModel

    # 建立串流 TTS 實例
    streaming_tts = EdgeTTSModel(voice="zh-TW-HsiaoChenNeural")

    # 建立 ASR 適配器（將同步方法包裝為異步）
    class ASRAdapter:
        def __init__(self, asr_service):
            self._asr = asr_service

        async def transcribe(self, audio_bytes: bytes) -> str:
            import asyncio
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            wav_path = tmp_path.replace(".webm", ".wav")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", tmp_path,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(f"ffmpeg failed: {stderr.decode()[:200]}")

                os.unlink(tmp_path)
                result = self._asr.transcribe(wav_path)
                return result.get("text", "")
            finally:
                for p in [tmp_path, wav_path]:
                    if os.path.exists(p):
                        os.unlink(p)

    # 建立 DM 適配器 - 整合真正的 LLM
    class DMAdapter:
        def __init__(self, session_id: str):
            self._session_id = session_id

        def process_input(self, text: str):
            """
            使用 LLM + ToolRegistry 處理用戶輸入
            返回 (回應文字, 購物車快照)
            """
            try:
                # 設置當前會話
                _tool_registry.set_session_id(self._session_id)

                # 確保會話存在
                session = _session_store.get(self._session_id)
                session.setdefault("llm_history", [])

                logger.info("[VOICE] LLM 處理: '{}', 當前購物車: {} 項", text, len(session.get('cart', [])))

                # 調用 LLM
                result = _llm_caller.run_turn(
                    system_prompt=SYSTEM_PROMPT,
                    user_text=text,
                    history=session["llm_history"],
                    tools_schema=_tool_registry.get_tools_schema(),
                    tool_map=_tool_registry.get_tool_map(),
                    allowed_args=_tool_registry.get_allowed_args(),
                )

                if result.get("ok"):
                    # 更新歷史
                    session["llm_history"] = result.get("history", [])
                    response_text = result.get("assistant_text", "")
                    if not response_text:
                        response_text = "好的，還需要什麼嗎？"

                    # 讀取更新後的購物車
                    cart = session.get("cart", [])
                    total_price = 0

                    # 計算總價
                    for item in cart:
                        qty = int(item.get("quantity", 1) or 1)
                        price_info = _dialogue_manager.get_price_info(item)
                        if price_info and price_info.get("status") == "success":
                            item_total = _dialogue_manager.extract_total(price_info, qty)
                            total_price += item_total

                    logger.info("[VOICE] LLM 回應: '{}', 購物車: {} 項, 總計: ${}", response_text, len(cart), total_price)

                    # 檢查是否有 finalize_order 結果
                    finalize_result = None
                    for trace in result.get("tool_trace", []):
                        tool_call = trace.get("tool_call", {})
                        if tool_call.get("function", {}).get("name") == "finalize_order":
                            exec_result = trace.get("exec", {})
                            if exec_result.get("ok"):
                                finalize_result = exec_result
                                break

                    return (response_text, {
                        "cart": cart,
                        "order_payload": {"total_price": total_price},
                        "finalize_result": finalize_result,
                    })
                else:
                    logger.error("[VOICE] LLM 錯誤: {}", result.get('error'))
                    return ("抱歉，系統暫時無法處理，請稍後再試。", {
                        "cart": [],
                        "order_payload": {"total_price": 0}
                    })

            except Exception as e:
                logger.exception("[VOICE] DMAdapter 異常")
                return (f"錯誤: {str(e)}", {
                    "cart": [],
                    "order_payload": {"total_price": 0}
                })

    asr_adapter = ASRAdapter(_asr_service)
    dm_adapter = DMAdapter(session_id)

    orchestrator = StreamingOrchestrator(asr_adapter, dm_adapter, streaming_tts, session_id=session_id)

    return StreamingResponse(
        event_generator(orchestrator, audio_bytes, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 緩衝
        }
    )
