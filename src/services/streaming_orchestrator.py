# src/services/streaming_orchestrator.py
import asyncio
import base64
import time
from typing import AsyncIterator, Dict, Any
from loguru import logger
from src.utils.perf_collector import perf_collector
from src.services.tts_cache import tts_cache
from src.dm import cart_manager

# 斷句標點 — 遇到就立即送 TTS
_SENTENCE_PUNCTS = set("，。？！、；：\n")


def _format_cart_items(cart: list) -> list:
    """將 raw session cart 轉換為前端 CartItem 格式 {name, details, price, quantity}"""
    items = []
    for item in cart:
        qty = int(item.get("quantity", 1) or 1)
        name = cart_manager.format_item(item)
        pi = cart_manager.get_price_info(item)
        if pi and pi.get("status") == "success":
            price = cart_manager.extract_total(pi, qty)
        else:
            price = 0
        items.append({
            "name": name,
            "details": "",
            "price": price,
            "quantity": qty,
        })
    return items


class StreamingOrchestrator:
    def __init__(self, asr_service, dialogue_manager, tts_service, session_id: str = None):
        self.asr = asr_service
        self.dm = dialogue_manager
        self.tts = tts_service
        self.session_id = session_id

    async def process_audio_stream(self, audio_bytes: bytes, session_id: str = None) -> AsyncIterator[Dict[str, Any]]:
        """原有流程（非串流 DM）— 保持向後相容"""
        if session_id:
            self.session_id = session_id

        request_start = time.perf_counter()
        logger.info("[SSE] 開始處理音訊串流, session_id={}", self.session_id)

        # 1. Thinking
        yield {"event": "thinking", "data": {}}

        # 2. ASR
        asr_start = time.perf_counter()
        text = await self.asr.transcribe(audio_bytes)
        asr_elapsed = time.perf_counter() - asr_start
        logger.info("[PERF] asr_transcribe 耗時 {:.3f}s", asr_elapsed)
        yield {"event": "transcription", "data": {"text": text}}

        if not text:
            logger.warning("[SSE] ASR 無法識別語音，中止處理")
            yield {"event": "error", "data": {"message": "無法識別語音內容，請再試一次"}}
            return

        # 3. DM
        dm_start = time.perf_counter()
        loop = asyncio.get_event_loop()
        response_text, context_snapshot = await loop.run_in_executor(None, self.dm.process_input, text)
        dm_elapsed = time.perf_counter() - dm_start
        logger.info("[PERF] dm_process 耗時 {:.3f}s", dm_elapsed)

        # 4. Cart Update
        cart = context_snapshot.get("cart", [])
        total = context_snapshot.get("order_payload", {}).get("total_price", 0)
        yield {"event": "cart_update", "data": {"items": _format_cart_items(cart), "total": total}}

        # 4.5 Order Complete（如果有 finalize_order 結果）
        finalize_result = context_snapshot.get("finalize_result")
        if finalize_result:
            yield {"event": "order_complete", "data": finalize_result}

        # 5. TTS — 先查快取，命中就直接 yield
        tts_start = time.perf_counter()
        ttfa_elapsed = None
        first_chunk = True

        cached = tts_cache.get(response_text)
        if cached:
            logger.info("[TTS-Cache] 命中快取: '{}'", response_text[:30])
            b64_audio = base64.b64encode(cached).decode('utf-8')
            yield {"event": "audio_chunk", "data": b64_audio}
            ttfa_elapsed = time.perf_counter() - request_start
            logger.info("[PERF] TTFA 首個音訊 {:.3f}s (快取命中)", ttfa_elapsed)
        else:
            async for chunk in self.tts.run_stream(response_text):
                b64_audio = base64.b64encode(chunk).decode('utf-8')
                yield {"event": "audio_chunk", "data": b64_audio}
                if first_chunk:
                    ttfa_elapsed = time.perf_counter() - request_start
                    logger.info("[PERF] TTFA 首個音訊 {:.3f}s", ttfa_elapsed)
                    first_chunk = False

        tts_elapsed = time.perf_counter() - tts_start
        logger.info("[PERF] tts_stream 耗時 {:.3f}s", tts_elapsed)

        total_elapsed = time.perf_counter() - request_start
        logger.info("[PERF] 端對端 SSE 總耗時 {:.3f}s", total_elapsed)

        # 記錄到效能收集器
        perf_collector.record(
            asr_s=asr_elapsed,
            dm_s=dm_elapsed,
            ttfa_s=ttfa_elapsed,
            tts_s=tts_elapsed,
            total_s=total_elapsed,
        )

    async def process_audio_stream_v2(self, audio_bytes: bytes, session_id: str = None) -> AsyncIterator[Dict[str, Any]]:
        """
        串流版流程：LLM 串流 + 分段 TTS
        DM adapter 須提供 process_input_stream() 方法
        """
        if session_id:
            self.session_id = session_id

        request_start = time.perf_counter()
        logger.info("[SSE-v2] 開始串流處理, session_id={}", self.session_id)

        # 1. Thinking
        yield {"event": "thinking", "data": {}}

        # 2. ASR
        asr_start = time.perf_counter()
        text = await self.asr.transcribe(audio_bytes)
        asr_elapsed = time.perf_counter() - asr_start
        logger.info("[PERF] asr_transcribe 耗時 {:.3f}s", asr_elapsed)
        yield {"event": "transcription", "data": {"text": text}}

        if not text:
            logger.warning("[SSE-v2] ASR 無法識別語音，中止處理")
            yield {"event": "error", "data": {"message": "無法識別語音內容，請再試一次"}}
            return

        # 3. DM 串流 — 逐句收 token，湊成句子後立即送 TTS
        dm_start = time.perf_counter()
        dm_elapsed = 0
        buffer = ""
        full_text = ""
        context_snapshot = {}
        first_audio = True
        ttfa_elapsed = None
        tts_start = None

        async for event in self.dm.process_input_stream(text):
            evt_type = event.get("type")

            if evt_type == "tool_call":
                # tool call 期間不產生音訊，但可以通知前端
                pass

            elif evt_type == "text_delta":
                content = event.get("content", "")
                buffer += content
                full_text += content

                # 檢查是否有完整句子可以送 TTS
                while buffer:
                    # 找第一個斷句標點
                    cut_idx = -1
                    for i, ch in enumerate(buffer):
                        if ch in _SENTENCE_PUNCTS:
                            cut_idx = i
                            break

                    if cut_idx == -1:
                        break  # 還沒湊成一句，繼續累積

                    sentence = buffer[:cut_idx + 1]
                    buffer = buffer[cut_idx + 1:]

                    if not sentence.strip():
                        continue

                    # 送 TTS
                    if tts_start is None:
                        tts_start = time.perf_counter()

                    # 先查快取
                    cached = tts_cache.get(sentence.strip())
                    if cached:
                        b64_audio = base64.b64encode(cached).decode('utf-8')
                        yield {"event": "audio_chunk", "data": b64_audio}
                        if first_audio:
                            ttfa_elapsed = time.perf_counter() - request_start
                            logger.info("[PERF] TTFA 首個音訊 {:.3f}s (快取命中)", ttfa_elapsed)
                            first_audio = False
                    else:
                        async for chunk in self.tts.run_stream(sentence):
                            b64_audio = base64.b64encode(chunk).decode('utf-8')
                            yield {"event": "audio_chunk", "data": b64_audio}
                            if first_audio:
                                ttfa_elapsed = time.perf_counter() - request_start
                                logger.info("[PERF] TTFA 首個音訊 {:.3f}s", ttfa_elapsed)
                                first_audio = False

            elif evt_type == "done":
                context_snapshot = event
                dm_elapsed = time.perf_counter() - dm_start
                logger.info("[PERF] dm_process_stream 耗時 {:.3f}s", dm_elapsed)

        # 處理 buffer 殘餘
        if buffer.strip():
            if tts_start is None:
                tts_start = time.perf_counter()
            cached = tts_cache.get(buffer.strip())
            if cached:
                b64_audio = base64.b64encode(cached).decode('utf-8')
                yield {"event": "audio_chunk", "data": b64_audio}
                if first_audio:
                    ttfa_elapsed = time.perf_counter() - request_start
                    first_audio = False
            else:
                async for chunk in self.tts.run_stream(buffer):
                    b64_audio = base64.b64encode(chunk).decode('utf-8')
                    yield {"event": "audio_chunk", "data": b64_audio}
                    if first_audio:
                        ttfa_elapsed = time.perf_counter() - request_start
                        first_audio = False

        # 4. Cart Update
        cart = context_snapshot.get("cart", [])
        total = context_snapshot.get("order_payload", {}).get("total_price", 0)
        yield {"event": "cart_update", "data": {"items": _format_cart_items(cart), "total": total}}

        # 4.5 Order Complete
        finalize_result = context_snapshot.get("finalize_result")
        if finalize_result:
            yield {"event": "order_complete", "data": finalize_result}

        tts_elapsed = (time.perf_counter() - tts_start) if tts_start else 0
        total_elapsed = time.perf_counter() - request_start
        logger.info("[PERF] tts_stream 耗時 {:.3f}s", tts_elapsed)
        logger.info("[PERF] 端對端 SSE 總耗時 {:.3f}s", total_elapsed)

        perf_collector.record(
            asr_s=asr_elapsed,
            dm_s=dm_elapsed,
            ttfa_s=ttfa_elapsed,
            tts_s=tts_elapsed,
            total_s=total_elapsed,
        )
