# src/services/streaming_orchestrator.py
import asyncio
import base64
import json
import re as _re
import time
from pathlib import Path
from datetime import datetime
from typing import AsyncIterator, Dict, Any
from loguru import logger
from src.utils.perf_collector import perf_collector
from src.services.tts_cache import tts_cache
from src.dm import cart_manager
from src.utils import SENTENCE_PUNCTS as _SENTENCE_PUNCTS

# 對話 log 目錄（lazy init，首次寫入時才建立）
_CONV_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "conversations"
_SAFE_ID_RE = _re.compile(r"[^\w\-]")


def _append_turn_log(session_id: str | None, turn: dict) -> None:
    """將單輪對話 trace append 到 session 的 JSONL 檔"""
    if not session_id:
        return
    _CONV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = _SAFE_ID_RE.sub("_", session_id)
    path = _CONV_LOG_DIR / f"{safe_id}.jsonl"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as e:
        logger.warning("[CONV_LOG] 寫入失敗: {}", e)


def _save_asr_pair(audio_path: Path, asr_text: str) -> None:
    """ASR 訓練資料：append 日 manifest.jsonl + 同名 .asr.txt
    manifest 為 source of truth 先寫（失敗代表沒 commit），.asr.txt 為人工編輯便利檔後寫
    """
    manifest_path = audio_path.parent / "manifest.jsonl"
    entry = {
        "audio": audio_path.name,
        "asr": asr_text,
        "ts": datetime.now().isoformat(),
    }
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # .asr.txt（不能用 with_suffix，.asr.txt 不是合法 single suffix）
    txt_path = audio_path.parent / f"{audio_path.stem}.asr.txt"
    txt_path.write_text(asr_text, encoding="utf-8")


# 自適應分句閾值
_MIN_SENTENCE_CHARS = 4  # 太短不送（繼續累積）
_MAX_SENTENCE_CHARS = 40  # 超長強制切（不等標點）

# tool call 中間狀態訊息
_TOOL_STATUS_MAP = {
    "add_item": "正在加入購物車...",
    "finalize_order": "正在確認訂單...",
    "preview_checkout": "正在準備結帳預覽...",
    "query_menu": "正在查詢菜單...",
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
        if pi and pi.get("ok"):
            price = cart_manager.extract_total(pi)
        else:
            price = 0
        items.append(
            {
                "name": name,
                "details": "",
                "price": price,
                "quantity": qty,
                "price_pending": cart_manager.is_item_price_pending(item),
            }
        )
    return items


class StreamingOrchestrator:
    def __init__(self, asr_service, dialogue_manager, tts_service, session_id: str = None):
        self.asr = asr_service
        self.dm = dialogue_manager
        self.tts = tts_service
        self.session_id = session_id

    async def _send_tts(
        self, text: str, request_start: float, first_audio: bool, label: str = ""
    ) -> AsyncIterator[tuple]:
        """TTS 音訊產生：查快取 → 命中直送 / miss 則串流。
        每個 yield 回傳 (sse_event, updated_first_audio, ttfa_or_None)"""
        # 清除 markdown 格式符號，避免 TTS 朗讀 * 等字元
        text = text.replace("*", "").replace("#", "").strip()
        if not text:
            return
        # voice_key 用於快取維度，區分 OmniVoice clone / instruct / Edge TTS 等不同聲音
        cached = tts_cache.get(text, voice_key=self.tts.cache_voice_key)
        if cached:
            b64 = base64.b64encode(cached).decode("utf-8")
            ttfa = None
            if first_audio:
                ttfa = time.perf_counter() - request_start
                logger.info("[PERF] TTFA {:.3f}s ({} 快取命中)", ttfa, label or "tts")
                first_audio = False
            yield {"event": "audio_chunk", "data": b64}, first_audio, ttfa
        else:
            # streamable：每個 chunk 都是獨立可播放音檔（如 VoxCPM MP3 段）→ 邊收邊下發，
            # TTFA 只等首段；否則（Edge frame 片段）收齊 join 後一次下發
            streamable = self.tts.stream_playable_chunks
            chunks = []
            try:
                async for chunk in self.tts.run_stream(text):
                    chunks.append(chunk)
                    if streamable:
                        b64 = base64.b64encode(chunk).decode("utf-8")
                        ttfa = None
                        if first_audio:
                            ttfa = time.perf_counter() - request_start
                            logger.info("[PERF] TTFA {:.3f}s ({})", ttfa, label or "tts")
                            first_audio = False
                        yield {"event": "audio_chunk", "data": b64}, first_audio, ttfa
            except Exception as e:
                # 串流中斷可能只產出半句 → 不入快取
                logger.warning("[TTS] {} run_stream 失敗: {}", label or "tts", e)
                return
            if not chunks:
                return
            audio = b"".join(chunks)
            # 以實際產出聲音的 key 存入（fallback 產物存 fallback 聲音 key，不污染本尊）
            tts_cache.put(text, audio, voice_key=self.tts.last_voice_key)
            if not streamable:
                b64 = base64.b64encode(audio).decode("utf-8")
                ttfa = None
                if first_audio:
                    ttfa = time.perf_counter() - request_start
                    logger.info("[PERF] TTFA {:.3f}s ({})", ttfa, label or "tts")
                    first_audio = False
                yield {"event": "audio_chunk", "data": b64}, first_audio, ttfa

    async def _run_dm_pipeline(
        self, text: str, request_start: float, asr_elapsed: float, log_prefix: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """共用的 DM → TTS 串流核心，供 audio/text 兩個入口共用"""
        dm_start = time.perf_counter()
        dm_elapsed = 0
        buffer = ""
        full_text = ""
        context_snapshot = {}
        first_audio = True
        ttfa_elapsed = None
        tts_start = None
        tool_calls_log: list[dict] = []

        async for event in self.dm.process_input_stream(text):
            evt_type = event.get("type")

            if evt_type == "tool_call":
                tc = event.get("tool_call", {})
                tool_name = tc.get("function", {}).get("name", "")
                status_msg = _TOOL_STATUS_MAP.get(tool_name, "處理中...")
                yield {"event": "status", "data": {"message": status_msg}}
                logger.info("[{}] tool_call status: {} → {}", log_prefix, tool_name, status_msg)
                tool_calls_log.append(
                    {
                        "name": tool_name,
                        "args": tc.get("function", {}).get("arguments"),
                        "result": event.get("tool_result"),
                    }
                )

            elif evt_type == "early_tts":
                early_text = event.get("content", "").strip()
                if early_text:
                    if tts_start is None:
                        tts_start = time.perf_counter()
                    async for evt, updated_first, ttfa in self._send_tts(
                        early_text, request_start, first_audio, "early_tts"
                    ):
                        yield evt
                        first_audio = updated_first
                        if ttfa is not None:
                            ttfa_elapsed = ttfa

            elif evt_type == "fallback":
                # LLM 超時或異常降級：送 TTS 友善回覆
                fallback_text = event.get("content", "").strip()
                if fallback_text:
                    full_text = fallback_text
                    if tts_start is None:
                        tts_start = time.perf_counter()
                    async for evt, updated_first, ttfa in self._send_tts(
                        fallback_text, request_start, first_audio, "fallback"
                    ):
                        yield evt
                        first_audio = updated_first
                        if ttfa is not None:
                            ttfa_elapsed = ttfa

            elif evt_type == "text_delta":
                content = event.get("content", "")
                buffer += content
                full_text += content

                # 即時轉發 text_delta 到前端（streaming 顯示）
                if content:
                    yield {"event": "text_delta", "data": {"text": content}}

                # 自適應分句：標點切分 + MIN/MAX 字數閾值
                while buffer:
                    if len(buffer) >= _MAX_SENTENCE_CHARS:
                        cut_idx = -1
                        for i, ch in enumerate(buffer[:_MAX_SENTENCE_CHARS]):
                            if ch in _SENTENCE_PUNCTS:
                                cut_idx = i
                        if cut_idx == -1:
                            cut_idx = _MAX_SENTENCE_CHARS - 1
                        sentence = buffer[: cut_idx + 1]
                        buffer = buffer[cut_idx + 1 :]
                    else:
                        cut_idx = -1
                        for i, ch in enumerate(buffer):
                            if ch in _SENTENCE_PUNCTS:
                                cut_idx = i
                                break
                        if cut_idx == -1:
                            break
                        sentence = buffer[: cut_idx + 1]
                        if len(sentence.strip()) < _MIN_SENTENCE_CHARS:
                            next_cut = -1
                            for i, ch in enumerate(buffer[cut_idx + 1 :]):
                                if ch in _SENTENCE_PUNCTS:
                                    next_cut = cut_idx + 1 + i
                                    break
                            if next_cut == -1:
                                break
                            sentence = buffer[: next_cut + 1]
                            cut_idx = next_cut
                        buffer = buffer[cut_idx + 1 :]

                    if not sentence.strip():
                        continue

                    if tts_start is None:
                        tts_start = time.perf_counter()
                    async for evt, updated_first, ttfa in self._send_tts(
                        sentence.strip(), request_start, first_audio, "sentence"
                    ):
                        yield evt
                        first_audio = updated_first
                        if ttfa is not None:
                            ttfa_elapsed = ttfa

            elif evt_type == "done":
                context_snapshot = event
                dm_elapsed = time.perf_counter() - dm_start
                logger.info("[PERF] dm_process_stream 耗時 {:.3f}s", dm_elapsed)

        # 提前送出 AI 回覆文字（在 TTS 殘餘之前，確保 Banner 及時顯示）
        if full_text.strip():
            yield {"event": "tts_text", "data": {"text": full_text}}

        # 處理 buffer 殘餘
        remaining = buffer.strip()
        if remaining:
            if tts_start is None:
                tts_start = time.perf_counter()
            async for evt, updated_first, ttfa in self._send_tts(
                remaining, request_start, first_audio, "buffer"
            ):
                yield evt
                first_audio = updated_first
                if ttfa is not None:
                    ttfa_elapsed = ttfa

        # Cart Update — total 由 items 加總，與顯示同源（不依賴 done 事件各生產者自算）
        cart = context_snapshot.get("cart", [])
        items = _format_cart_items(cart)
        total = sum(i["price"] for i in items)
        # has_pending 不另送：前端/腳本由 items 的 price_pending 自行 derive，單一來源
        yield {"event": "cart_update", "data": {"items": items, "total": total}}

        # Order Complete
        finalize_result = context_snapshot.get("finalize_result")
        if finalize_result:
            yield {"event": "order_complete", "data": finalize_result}

        # Checkout Preview（preview_checkout tool 結果）
        preview_result = context_snapshot.get("preview_result")
        if preview_result and preview_result.get("preview"):
            yield {
                "event": "checkout_preview",
                "data": {
                    "dine_type": preview_result.get("dine_type"),
                    "payment_method": preview_result.get("payment_method"),
                },
            }

        tts_elapsed = (time.perf_counter() - tts_start) if tts_start else 0
        total_elapsed = time.perf_counter() - request_start
        logger.info("[PERF] tts_stream 耗時 {:.3f}s", tts_elapsed)
        logger.info("[PERF] {} 端對端耗時 {:.3f}s", log_prefix, total_elapsed)

        perf_collector.record(
            asr_s=asr_elapsed,
            dm_s=dm_elapsed,
            ttfa_s=ttfa_elapsed,
            tts_s=tts_elapsed,
            total_s=total_elapsed,
        )

        _append_turn_log(
            self.session_id,
            {
                "ts": datetime.now().isoformat(),
                "asr_text": f"[{log_prefix}] {text}" if log_prefix != "SSE-v2" else text,
                "tool_calls": tool_calls_log,
                "response": full_text,
                "cart_count": len(cart),
                "perf": {
                    "asr_s": round(asr_elapsed, 3),
                    "dm_s": round(dm_elapsed, 3),
                    "ttfa_s": round(ttfa_elapsed, 3) if ttfa_elapsed else None,
                    "tts_s": round(tts_elapsed, 3),
                    "total_s": round(total_elapsed, 3),
                },
            },
        )

    async def process_audio_stream_v2(
        self,
        audio_bytes: bytes,
        session_id: str = None,
        audio_path: Path | None = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """串流版流程：ASR → DM 串流 → 分段 TTS

        Args:
            audio_path: 若提供，ASR 成功後會寫 .asr.txt 同名配對檔 + manifest.jsonl
                        供後續 ASR/LLM 訓練資料建構使用
        """
        if session_id:
            self.session_id = session_id

        request_start = time.perf_counter()
        logger.info("[SSE-v2] 開始串流處理, session_id={}", self.session_id)

        yield {"event": "thinking", "data": {}}

        # ASR
        asr_start = time.perf_counter()
        try:
            text = await self.asr.transcribe(audio_bytes)
        except Exception as e:
            logger.error("[SSE-v2] ASR transcribe 異常: {}", e)
            yield {"event": "error", "data": {"message": "語音辨識失敗，請再試一次"}}
            return
        asr_elapsed = time.perf_counter() - asr_start
        logger.info("[PERF] asr_transcribe 耗時 {:.3f}s", asr_elapsed)
        yield {"event": "transcription", "data": {"text": text}}

        # 推送 monitor 事件（純觀察用，無訂閱者時為 no-op）
        from src.api.pipeline_event_broadcaster import pipeline_broadcaster

        pipeline_broadcaster.emit(
            "asr_done",
            self.session_id or "",
            {"text": text, "latency_ms": int(asr_elapsed * 1000)},
        )

        # 訓練資料：音訊 + ASR 文字 pair 存檔（offload 到 executor 不阻塞 event loop，對齊 voice_router webm 存檔）
        if audio_path and text:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _save_asr_pair, audio_path, text)
            except (OSError, TypeError, ValueError) as e:
                logger.warning("[ASR_PAIR] 寫入失敗: {}", e)

        if not text:
            logger.warning("[SSE-v2] ASR 無法識別語音，中止處理")
            yield {"event": "error", "data": {"message": "無法識別語音內容，請再試一次"}}
            return

        async for evt in self._run_dm_pipeline(text, request_start, asr_elapsed, "SSE-v2"):
            yield evt

    async def process_text_stream(
        self, text: str, session_id: str = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """純文字輸入版：跳過 ASR，直接進 DM → TTS pipeline"""
        if session_id:
            self.session_id = session_id

        request_start = time.perf_counter()
        logger.info(
            "[SSE-text] 開始純文字串流處理, session_id={}, text='{}'", self.session_id, text
        )

        yield {"event": "thinking", "data": {}}
        yield {"event": "transcription", "data": {"text": text}}

        if not text:
            yield {"event": "error", "data": {"message": "輸入文字不能為空"}}
            return

        async for evt in self._run_dm_pipeline(text, request_start, 0, "text-input"):
            yield evt
