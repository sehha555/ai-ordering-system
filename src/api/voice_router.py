# src/api/voice_router.py
from fastapi import APIRouter, UploadFile, File, Depends, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio
import json
from loguru import logger

from src.services.asr_postprocess import postprocess
from src.services.streaming_orchestrator import StreamingOrchestrator
from src.services.tts_implementations import create_tts_model
from src.config.models import TTS_BACKEND
from src.api.auth import get_api_key
from src.dm.tool_priming import CHECKOUT_TAG

import re

# 結帳狀態機常數
_CK_DINE = "CHECKOUT_DINE"
_CK_PAY = "CHECKOUT_PAY"
_CK_STATES = (_CK_DINE, _CK_PAY)

# 偵測點餐意圖的關鍵字（結帳中反悔 → 退出結帳回 LLM）
_ORDER_INTENT_KEYWORDS = [
    "飯糰",
    "蛋餅",
    "吐司",
    "漢堡",
    "饅頭",
    "鐵板麵",
    "薯餅",
    "蘿蔔糕",
    "蔥抓餅",
    "餡餅",
    "點心",
    "果醬吐司",
    "豆漿",
    "奶茶",
    "紅茶",
    "綠茶",
    "咖啡",
    "果汁",
    "套餐",
    "加一",
    "再一",
    "多一",
    "還要",
    "點一",
    "來一",
    "給我",
    "我要",
]

# [REMOVE] tag 正則
_REMOVE_RE = re.compile(r"\[REMOVE:(.+?)\]")

# [ADD:品項名|key=value|...] — 點餐 tag
_ADD_RE = re.compile(r"\[ADD:([^\]]+)\]")

# [QUERY:分類] 或 [QUERY] — 菜單查詢 tag
_QUERY_RE = re.compile(r"\[QUERY(?::([^\]]*))?\]")

# 規則層攔截常數
_EMPTY_CART_MOD_KEYWORDS = ["刪掉", "移除", "撤銷", "取消上一", "刪掉剛剛"]
_DRINK_INQUIRY_PATTERNS = [
    "有什麼飲料",
    "飲料有什麼",
    "有哪些飲料",
    "喝的有什麼",
    "飲品有什麼",
    "有什麼喝的",
]

router = APIRouter()

# 啟動時初始化 TTS（避免每次 request 重新載入模型）
_streaming_tts = create_tts_model(TTS_BACKEND)


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

    # ── 結帳狀態機：keyword parsing ──

    @staticmethod
    def _parse_dine_type(text: str) -> str | None:
        t = text.strip()
        if any(kw in t for kw in ["內用", "這裡吃", "在這吃", "在這裡", "dine"]):
            return "dine-in"
        if any(kw in t for kw in ["外帶", "帶走", "打包", "take"]):
            return "take-out"
        return None

    @staticmethod
    def _parse_payment(text: str) -> str | None:
        t = text.strip()
        if any(kw in t for kw in ["現金", "cash"]):
            return "cash"
        if any(kw in t for kw in ["Line", "line", "行動", "支付", "pay", "Pay", "LINE"]):
            return "line_pay"
        return None

    @staticmethod
    def _has_order_intent(text: str) -> bool:
        """檢查 text 是否包含點餐意圖關鍵字"""
        return any(kw in text for kw in _ORDER_INTENT_KEYWORDS)

    @staticmethod
    def _patch_last_assistant(history: list[dict], content: str) -> None:
        """覆寫 history 中最後一條 assistant 回覆"""
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                msg["content"] = content
                return

    def _exit_checkout(self, session: dict, _session_store) -> None:
        """清除結帳狀態並回寫 session（反悔出口用）"""
        session.pop("checkout_status", None)
        session.pop("checkout_dine_type", None)
        _session_store.set(self._session_id, session)

    async def _shortcircuit_reply(
        self, text: str, reply: str, session: dict, _session_store, cart: list
    ):
        """規則層攔截共用：寫入 history、回寫 session、yield text_delta + done。"""
        from src.dm import cart_manager

        session["llm_history"].append({"role": "user", "content": text})
        session["llm_history"].append({"role": "assistant", "content": reply})
        _session_store.set(self._session_id, session)
        yield {"type": "text_delta", "content": reply}
        yield {
            "type": "done",
            "cart": cart,
            "order_payload": {"total_price": cart_manager.calculate_cart_total(cart)},
            "finalize_result": None,
            "preview_result": None,
        }

    async def _checkout_step(self, text: str, session: dict):
        """結帳狀態機：根據 checkout_status 處理 user input，不經 LLM。
        未 yield 任何事件 = 反悔退出，caller 應 fallthrough 到 LLM。
        """
        from src.services import container
        from src.dm import cart_manager

        _session_store = container.session_store
        _tool_registry = container.tool_registry
        _tool_registry.set_session_id(self._session_id)

        status = session.get("checkout_status")

        reply = None
        finalize_result = None

        if status == _CK_DINE:
            dine = self._parse_dine_type(text)
            if dine:
                session["checkout_dine_type"] = dine
                session["checkout_status"] = _CK_PAY
                reply = "現金還是行動支付？"
            elif self._has_order_intent(text):
                # 反悔：intent 檢查必須在 parse 失敗後才執行
                self._exit_checkout(session, _session_store)
                return
            else:
                reply = "請問是內用還是外帶？"

        elif status == _CK_PAY:
            pay = self._parse_payment(text)
            if pay:
                dine = session.get("checkout_dine_type")
                if dine is None:
                    logger.warning("[CHECKOUT] checkout_dine_type missing in CHECKOUT_PAY state")
                    dine = "dine-in"
                result = _tool_registry.finalize_order(
                    dine_type=dine,
                    payment_method=pay,
                )
                session.pop("checkout_status", None)
                session.pop("checkout_dine_type", None)
                if result.get("ok"):
                    finalize_result = result
                    order_number = result.get("order_number", "")
                    reply = f"好，{order_number}號～"
                else:
                    reply = result.get("message", "結帳失敗，請再試一次")
            elif self._has_order_intent(text):
                # 反悔：intent 檢查必須在 parse 失敗後才執行
                self._exit_checkout(session, _session_store)
                return
            else:
                reply = "請問要現金還是行動支付？"

        # 追加對話歷史
        session["llm_history"].append({"role": "user", "content": text})
        session["llm_history"].append({"role": "assistant", "content": reply})
        _session_store.set(self._session_id, session)

        # yield text_delta（給 orchestrator 做 TTS）
        yield {"type": "text_delta", "content": reply}

        # yield done（僅結帳完成時計算總價）
        cart = session.get("cart", [])
        total_price = cart_manager.calculate_cart_total(cart) if finalize_result else 0
        yield {
            "type": "done",
            "cart": cart,
            "order_payload": {"total_price": total_price},
            "finalize_result": finalize_result,
            "preview_result": None,
        }

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

        # ── 結帳狀態機攔截：不經 LLM ──
        if session.get("checkout_status") in _CK_STATES:
            yielded = False
            async for evt in self._checkout_step(text, session):
                yielded = True
                yield evt
            if yielded:
                return
            # 反悔出口：_checkout_step 已 in-place 清除狀態並回寫，直接 fallthrough

        # ── 規則層攔截（pre-LLM）──
        cart = session.get("cart", [])

        # 1. 空購物車 + 修改意圖
        if not cart and any(kw in text for kw in _EMPTY_CART_MOD_KEYWORDS):
            async for evt in self._shortcircuit_reply(
                text, "購物車是空的，請先點餐喔！", session, _session_store, cart
            ):
                yield evt
            return

        # 2. 俗稱正規化（大冰奶 → 大杯冰純鮮奶茶，交由 order_router.NORMALIZE_MAP 維護）
        from src.tools.order_router import normalize_text

        text = normalize_text(text)

        # 3. 飲料查詢強制攔截
        if any(pat in text for pat in _DRINK_INQUIRY_PATTERNS):
            menu_result = _tool_registry.query_menu(category="飲品")
            if menu_result.get("ok"):
                items = menu_result.get("items", [])
                available = [i["name"] for i in items if i.get("available")]
                sold_out = [i["name"] for i in items if not i.get("available")]
                reply = f"我們的飲品有：{'、'.join(available)}"
                if sold_out:
                    reply += f"（目前售完：{'、'.join(sold_out)}）"
                reply += "，請問要點什麼呢？"
            else:
                reply = "抱歉，無法查詢飲品菜單，請再試一次。"
            async for evt in self._shortcircuit_reply(text, reply, session, _session_store, cart):
                yield evt
            return

        logger.info(
            "[VOICE-STREAM] LLM 串流處理: '{}', 購物車: {} 項", text, len(session.get("cart", []))
        )

        # 構建動態上下文（購物車/待補槽）
        ctx = build_context_message(SessionContext.from_session(session))

        full_text = ""
        tool_trace = []

        try:
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
                    tool_trace.append(
                        {"tool_call": event.get("tool_call"), "exec": event.get("exec")}
                    )
                    yield event

                elif evt_type == "done":
                    full_text = event.get("assistant_text", "")
                    session["llm_history"] = event.get("history", [])

                    if not full_text:
                        full_text = "好的，還需要什麼嗎？"

                    # ── [CHECKOUT] 攔截 ──
                    if CHECKOUT_TAG in full_text:
                        cart = session.get("cart", [])
                        if not cart:
                            full_text = "購物車是空的，請先點餐喔～"
                        else:
                            session["checkout_status"] = _CK_DINE
                            full_text = full_text.replace(CHECKOUT_TAG, "")
                        self._patch_last_assistant(session["llm_history"], full_text)

                    # ── [REMOVE:...] 攔截 ──
                    if "[REMOVE:" in full_text:
                        remove_match = _REMOVE_RE.search(full_text)
                        if remove_match:
                            remove_target = remove_match.group(1).strip()
                            cart = session.get("cart", [])
                            remove_result: dict = {"ok": False, "message": "移除失敗"}

                            if remove_target == "all":
                                remove_result = _tool_registry.remove_from_cart(all=True)
                            elif remove_target == "last":
                                remove_result = _tool_registry.remove_from_cart(last=True)
                            else:
                                matched_id = None
                                for item in cart:
                                    if remove_target in cart_manager.format_item(item):
                                        matched_id = item.get("item_id")
                                        break
                                if matched_id:
                                    remove_result = _tool_registry.remove_from_cart(
                                        item_id=matched_id
                                    )
                                else:
                                    remove_result = {
                                        "ok": False,
                                        "message": f"購物車裡沒有{remove_target}",
                                    }

                            full_text = _REMOVE_RE.sub("", full_text).strip()
                            if not full_text:
                                msg_text = remove_result.get("message", "已移除")
                                full_text = f"{msg_text}～還需要什麼？"
                            self._patch_last_assistant(session["llm_history"], full_text)

                    # ── [ADD:品項名|key=value|...] 攔截 ──
                    if "[ADD:" in full_text:
                        for add_content in _ADD_RE.findall(full_text):
                            parts = add_content.split("|")
                            item_name = parts[0].strip()
                            kwargs: dict = {"name": item_name}
                            for part in parts[1:]:
                                if "=" in part:
                                    key, value = part.split("=", 1)
                                    key = key.strip()
                                    value = value.strip()
                                    if key == "qty":
                                        try:
                                            kwargs["quantity"] = int(value)
                                        except ValueError:
                                            pass
                                    elif key in ("rice", "size", "temp", "flavor"):
                                        kwargs[key] = value
                                    elif key in ("spicy", "extra_egg"):
                                        kwargs[key] = value.lower() == "true"
                            add_result = _tool_registry.add_item(**kwargs)
                            if not add_result.get("ok"):
                                logger.warning(
                                    "[ADD tag] 執行失敗: {} → {}",
                                    add_content,
                                    add_result.get("message"),
                                )
                        full_text = _ADD_RE.sub("", full_text).strip()
                        self._patch_last_assistant(session["llm_history"], full_text)

                    # ── [QUERY:分類] 攔截 ──
                    if "[QUERY" in full_text:
                        query_match = _QUERY_RE.search(full_text)
                        if query_match:
                            category = query_match.group(1)
                            if category:
                                category = category.strip() or None
                            else:
                                category = None
                            query_result = _tool_registry.query_menu(category=category)
                            logger.info(
                                "[QUERY tag] category={} → {} 項",
                                category,
                                query_result.get("count", 0),
                            )
                        full_text = _QUERY_RE.sub("", full_text).strip()
                        self._patch_last_assistant(session["llm_history"], full_text)

                    _session_store.set(self._session_id, session)

                    # 讀取購物車
                    cart = session.get("cart", [])
                    total_price = cart_manager.calculate_cart_total(cart)

                    # 檢查 finalize_order
                    finalize_result = None
                    preview_result = None
                    for trace in event.get("tool_trace", []):
                        tc = trace.get("tool_call", {})
                        tool_name = tc.get("function", {}).get("name")
                        if tool_name == "finalize_order":
                            exec_r = trace.get("exec", {})
                            if exec_r.get("ok"):
                                finalize_result = exec_r
                        elif tool_name == "preview_checkout":
                            exec_r = trace.get("exec", {})
                            if exec_r.get("ok") and exec_r.get("preview"):
                                preview_result = exec_r

                    yield {
                        "type": "done",
                        "cart": cart,
                        "order_payload": {"total_price": total_price},
                        "finalize_result": finalize_result,
                        "preview_result": preview_result,
                    }

        except Exception as e:
            logger.error("[VOICE-STREAM] LLM 不可用，觸發降級: {}", e)
            yield {"type": "fallback", "content": "不好意思，系統暫時無法回應，請再說一次"}
            yield {
                "type": "done",
                "cart": session.get("cart", []),
                "order_payload": {"total_price": 0},
                "finalize_result": None,
                "preview_result": None,
            }


class TextChatRequest(BaseModel):
    """純文字輸入請求（用於自動追問等跳過 ASR 的場景）"""

    text: str = Field(..., max_length=500)
    session_id: str


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/text-chat")
async def text_chat(request: TextChatRequest, api_key: str = Depends(get_api_key)):
    """
    純文字對話 SSE 端點（跳過 ASR）

    接收文字 + session_id，返回 Server-Sent Events 串流：
    - 與 /voice-chat 事件格式完全相同
    - 用途：自動追問、文字輸入模式等不需要語音辨識的場景
    """
    logger.info(
        "[TEXT-CHAT] 收到文字請求: session_id={}, text='{}'", request.session_id, request.text
    )

    dm_adapter = StreamingDMAdapter(request.session_id)
    orchestrator = StreamingOrchestrator(
        None, dm_adapter, _streaming_tts, session_id=request.session_id
    )
    return StreamingResponse(
        _sse_wrap(
            orchestrator.process_text_stream(request.text, session_id=request.session_id), "text"
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/voice-chat")
async def voice_chat(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    api_key: str = Depends(get_api_key),
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

    from src.config.settings import settings

    if len(audio_bytes) > settings.MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="音訊檔案超過 10MB 上限")

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
                "ffmpeg",
                "-y",
                "-i",
                "pipe:0",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            wav_bytes, stderr_bytes = await proc.communicate(input=audio_bytes)

            if proc.returncode != 0 or not wav_bytes:
                stderr_msg = (stderr_bytes or b"")[:500].decode(errors="replace")
                logger.warning(
                    "[ASR] ffmpeg 轉換失敗（returncode={}）: {}", proc.returncode, stderr_msg
                )
                return ""

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._asr.transcribe_bytes, wav_bytes)
            asr_error = result.get("error")
            if asr_error:
                logger.warning("[ASR] 辨識錯誤: {}", asr_error)
            return postprocess(result.get("text", ""))

    asr_adapter = ASRAdapter(_asr_service)
    dm_adapter = StreamingDMAdapter(session_id)
    orchestrator = StreamingOrchestrator(
        asr_adapter, dm_adapter, streaming_tts, session_id=session_id
    )
    return StreamingResponse(
        _sse_wrap(
            orchestrator.process_audio_stream_v2(audio_bytes, session_id=session_id), "voice"
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
