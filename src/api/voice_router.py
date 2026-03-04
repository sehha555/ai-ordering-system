# src/api/voice_router.py
from fastapi import APIRouter, UploadFile, File, Depends, Form
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
import asyncio
import json
import os
import tempfile
from loguru import logger

from src.services.asr_postprocess import postprocess
from src.services.streaming_orchestrator import StreamingOrchestrator
from src.services.tts_implementations import create_tts_model
from src.config.models import TTS_BACKEND
from src.config.settings import settings

router = APIRouter()

# 啟動時初始化 TTS（避免每次 request 重新載入模型）
_streaming_tts = create_tts_model(TTS_BACKEND)

# API Key 驗證
API_KEY = settings.API_KEY
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key_optional(api_key: str = Depends(api_key_header)):
    """可選的 API Key 驗證（用於開發測試）"""
    return api_key


async def _sse_wrap(stream, label: str):
    """將 orchestrator 的 event stream 包裝為 SSE 格式（全域 try/except 防止靜默斷線）"""
    try:
        async for event in stream:
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error("[SSE-{}] 未捕捉異常: {}", label, e)
        error_data = json.dumps({"message": "伺服器處理錯誤，請再試一次"}, ensure_ascii=False)
        yield f"event: error\ndata: {error_data}\n\n"


class StreamingDMAdapter:
    """串流版 DM 適配器 — 提供 process_input_stream() 方法"""

    def __init__(self, session_id: str):
        self._session_id = session_id

    async def process_input_stream(self, text: str):
        """串流版：逐 token yield LLM 回應，提供給 orchestrator 做分段 TTS"""
        from src.services import container
        from src.dm import cart_manager
        from src.dm.system_prompts import build_context_message, SystemPromptBuilder
        from src.dm.session_context import SessionContext

        _session_store = container.session_store
        _llm_caller = container.llm_caller
        _tool_registry = container.tool_registry

        _tool_registry.set_session_id(self._session_id)
        session = _session_store.get(self._session_id)
        session.setdefault("llm_history", [])

        logger.info("[VOICE-STREAM] LLM 串流處理: '{}', 購物車: {} 項", text, len(session.get('cart', [])))

        # 構建動態上下文（購物車/待補槽）
        ctx = build_context_message(SessionContext.from_session(session))

        full_text = ""
        tool_trace = []

        async for event in _llm_caller.run_turn_stream(
            system_prompt=SystemPromptBuilder().build(),
            user_text=text,
            history=session["llm_history"],
            tools_schema=_tool_registry.get_tools_schema(),
            tool_map=_tool_registry.get_tool_map(),
            allowed_args=_tool_registry.get_allowed_args(),
            context=ctx,
        ):
            evt_type = event.get("type")

            if evt_type == "text_delta":
                yield event

            elif evt_type == "early_tts":
                yield event  # pass through 給 orchestrator 立即送 TTS

            elif evt_type == "tool_call":
                tool_trace.append({"tool_call": event.get("tool_call"), "exec": event.get("exec")})
                yield event

            elif evt_type == "done":
                full_text = event.get("assistant_text", "")
                session["llm_history"] = event.get("history", [])
                _session_store.set(self._session_id, session)  # Redis 回寫

                if not full_text:
                    full_text = "好的，還需要什麼嗎？"

                # 讀取購物車
                cart = session.get("cart", [])
                total_price = cart_manager.calculate_cart_total(cart)

                # 檢查 finalize_order
                finalize_result = None
                for trace in event.get("tool_trace", []):
                    tc = trace.get("tool_call", {})
                    if tc.get("function", {}).get("name") == "finalize_order":
                        exec_r = trace.get("exec", {})
                        if exec_r.get("ok"):
                            finalize_result = exec_r
                            break

                yield {
                    "type": "done",
                    "cart": cart,
                    "order_payload": {"total_price": total_price},
                    "finalize_result": finalize_result,
                }


class TextChatRequest(BaseModel):
    """純文字輸入請求（用於自動追問等跳過 ASR 的場景）"""
    text: str
    session_id: str


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/text-chat")
async def text_chat(
    request: TextChatRequest,
    api_key: str = Depends(get_api_key_optional)
):
    """
    純文字對話 SSE 端點（跳過 ASR）

    接收文字 + session_id，返回 Server-Sent Events 串流：
    - 與 /voice-chat 事件格式完全相同
    - 用途：自動追問、文字輸入模式等不需要語音辨識的場景
    """
    logger.info("[TEXT-CHAT] 收到文字請求: session_id={}, text='{}'", request.session_id, request.text)

    dm_adapter = StreamingDMAdapter(request.session_id)
    orchestrator = StreamingOrchestrator(None, dm_adapter, _streaming_tts, session_id=request.session_id)
    return StreamingResponse(
        _sse_wrap(orchestrator.process_text_stream(request.text, session_id=request.session_id), "text"),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


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

    # 估算時長：webm/opus 通常 ~32kbps，過短視為空白音訊跳過 ASR
    estimated_duration_ms = len(audio_bytes) / (32 * 1024 / 8) * 1000
    if estimated_duration_ms < 200:
        logger.debug("[VOICE] 音訊過短（估計 {}ms），跳過 ASR", int(estimated_duration_ms))

        async def _empty_stream():
            yield {"event": "done", "data": {"cart": [], "order_payload": {"total_price": 0}}}

        return StreamingResponse(
            _sse_wrap(_empty_stream(), "empty"),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    # 取得服務實例（從服務容器導入）
    from src.services import container
    _asr_service = container.asr_service

    # 使用啟動時已載入的 TTS 實例
    streaming_tts = _streaming_tts

    # 建立 ASR 適配器（將同步方法包裝為異步）
    class ASRAdapter:
        def __init__(self, asr_service):
            self._asr = asr_service

        async def transcribe(self, audio_bytes: bytes) -> str:
            # pipe 模式：webm bytes → ffmpeg stdin → wav bytes（省去 webm 磁碟 I/O）
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", "pipe:0",
                "-ar", "16000", "-ac", "1",
                "-f", "wav", "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            wav_bytes, _ = await proc.communicate(input=audio_bytes)

            if proc.returncode != 0 or not wav_bytes:
                logger.warning("[ASR] ffmpeg 轉換失敗（returncode={}）", proc.returncode)
                return ""

            # ASR service 只接受 file path，寫入 wav tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
                tmp_wav.write(wav_bytes)
                wav_path = tmp_wav.name

            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self._asr.transcribe, wav_path)
                asr_error = result.get("error")
                if asr_error:
                    logger.warning("[ASR] 辨識錯誤: {}", asr_error)
                return postprocess(result.get("text", ""))
            finally:
                try:
                    os.unlink(wav_path)
                except FileNotFoundError:
                    pass

    asr_adapter = ASRAdapter(_asr_service)
    dm_adapter = StreamingDMAdapter(session_id)
    orchestrator = StreamingOrchestrator(asr_adapter, dm_adapter, streaming_tts, session_id=session_id)
    return StreamingResponse(
        _sse_wrap(orchestrator.process_audio_stream_v2(audio_bytes, session_id=session_id), "voice"),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
