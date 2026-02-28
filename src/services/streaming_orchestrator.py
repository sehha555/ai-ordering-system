# src/services/streaming_orchestrator.py
import base64
import time
from typing import AsyncIterator, Dict, Any
from loguru import logger
from src.utils.perf_collector import perf_collector
from src.services.tts_cache import tts_cache
from src.dm import cart_manager

# 斷句標點 — 遇到就立即送 TTS
_SENTENCE_PUNCTS = set("，。？！、；：\n")

# 自適應分句閾值
_MIN_SENTENCE_CHARS = 4   # 太短不送（繼續累積）
_MAX_SENTENCE_CHARS = 40  # 超長強制切（不等標點）

# tool call 中間狀態訊息
_TOOL_STATUS_MAP = {
    "add_to_cart": "正在加入購物車...",
    "finalize_order": "正在確認訂單...",
    "query_menu": "正在查詢菜單...",
    "get_price": "正在查詢價格...",
    "remove_from_cart": "正在移除品項...",
    "get_cart_summary": "正在整理購物車...",
}


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
                # 送 status event 給前端顯示（純文字，不發 TTS 音訊）
                tool_name = event.get("tool_call", {}).get("function", {}).get("name", "")
                status_msg = _TOOL_STATUS_MAP.get(tool_name, "處理中...")
                yield {"event": "status", "data": {"message": status_msg}}
                logger.info("[SSE-v2] tool_call status: {} → {}", tool_name, status_msg)

            elif evt_type == "text_delta":
                content = event.get("content", "")
                buffer += content
                full_text += content

                # 自適應分句：標點切分 + MIN/MAX 字數閾值
                while buffer:
                    # 強制切：buffer 超過最大字數，不等標點
                    if len(buffer) >= _MAX_SENTENCE_CHARS:
                        # 找最近的標點（在 MAX 範圍內）
                        cut_idx = -1
                        for i, ch in enumerate(buffer[:_MAX_SENTENCE_CHARS]):
                            if ch in _SENTENCE_PUNCTS:
                                cut_idx = i
                        if cut_idx == -1:
                            # 沒有標點，強制在 MAX 處截斷
                            cut_idx = _MAX_SENTENCE_CHARS - 1
                        sentence = buffer[:cut_idx + 1]
                        buffer = buffer[cut_idx + 1:]
                    else:
                        # 找第一個斷句標點
                        cut_idx = -1
                        for i, ch in enumerate(buffer):
                            if ch in _SENTENCE_PUNCTS:
                                cut_idx = i
                                break

                        if cut_idx == -1:
                            break  # 還沒湊成一句，繼續累積

                        sentence = buffer[:cut_idx + 1]

                        # 最小字數檢查：太短就繼續累積，等下一個標點
                        if len(sentence.strip()) < _MIN_SENTENCE_CHARS:
                            # 把下一段也納進來再找下一個標點
                            next_cut = -1
                            for i, ch in enumerate(buffer[cut_idx + 1:]):
                                if ch in _SENTENCE_PUNCTS:
                                    next_cut = cut_idx + 1 + i
                                    break
                            if next_cut == -1:
                                break  # 後面還沒有標點，繼續累積
                            # 合併到下一個標點
                            sentence = buffer[:next_cut + 1]
                            cut_idx = next_cut

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

        # 3.5 送出 AI 回覆文字給前端橫幅顯示
        yield {"event": "tts_text", "data": {"text": full_text}}

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
