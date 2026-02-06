# src/api/voice_router.py
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
import json
import os

from src.services.streaming_orchestrator import StreamingOrchestrator

router = APIRouter()

# API Key 驗證
API_KEY = os.getenv("API_KEY", "yuan-secret-key")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key_optional(api_key: str = Depends(api_key_header)):
    """可選的 API Key 驗證（用於開發測試）"""
    return api_key


async def event_generator(orchestrator: StreamingOrchestrator, audio_bytes: bytes):
    """將 orchestrator 事件轉換為 SSE 格式"""
    async for event in orchestrator.process_audio_stream(audio_bytes):
        # Format as SSE
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"


@router.post("/voice-chat")
async def voice_chat(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key_optional)
):
    """
    語音對話 SSE 端點

    接收音訊檔案，返回 Server-Sent Events 串流：
    - event: thinking     - 開始處理
    - event: transcription - ASR 轉錄結果
    - event: cart_update  - 購物車更新
    - event: audio_chunk  - TTS 音訊片段 (base64)
    """
    audio_bytes = await file.read()

    # 取得服務實例（從 app.py 導入）
    # 這裡使用延遲導入避免循環依賴
    from src.api.app import _asr_service, _dialogue_manager, _tts_service
    from src.services.tts_implementations import EdgeTTSModel

    # 建立串流 TTS 實例
    streaming_tts = EdgeTTSModel(voice="zh-TW-HsiaoChenNeural")

    # 建立 ASR 適配器（將同步方法包裝為異步）
    class ASRAdapter:
        def __init__(self, asr_service):
            self._asr = asr_service

        async def transcribe(self, audio_bytes: bytes) -> str:
            import tempfile
            import subprocess

            # 保存音訊到臨時檔案
            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                # 轉換為 WAV
                wav_path = tmp_path.replace(".webm", ".wav")
                subprocess.run([
                    "ffmpeg", "-y", "-i", tmp_path,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav_path
                ], capture_output=True, check=True)
                os.unlink(tmp_path)

                # 執行 ASR
                result = self._asr.transcribe(wav_path)
                return result.get("text", "")
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)

    # 建立 DM 適配器
    class DMAdapter:
        def __init__(self, dm):
            self._dm = dm

        def process_input(self, text: str):
            # 簡化版本：直接返回確認訊息
            # 完整版本需要整合 LLM
            return (f"好的，收到：{text}", {"cart": [], "order_payload": {"total_price": 0}})

    asr_adapter = ASRAdapter(_asr_service)
    dm_adapter = DMAdapter(_dialogue_manager)

    orchestrator = StreamingOrchestrator(asr_adapter, dm_adapter, streaming_tts)

    return StreamingResponse(
        event_generator(orchestrator, audio_bytes),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 緩衝
        }
    )
