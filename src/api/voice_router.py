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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_AUDIO_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "audio"

# [REMOVE] tag 正則
_REMOVE_RE = re.compile(r"\[REMOVE:(.+?)\]")

# [ADD:品項名|key=value|...] — 點餐 tag
_ADD_RE = re.compile(r"\[ADD:([^\]]+)\]")

# [SET_QTY:品項|qty=N] — 修改數量 tag
_SET_QTY_RE = re.compile(r"\[SET_QTY:([^\]]+)\]")

# [QUERY:分類] 或 [QUERY] — 菜單查詢 tag
_QUERY_RE = re.compile(r"\[QUERY(?::([^\]]*))?\]")


def _find_cart_item_id(cart: list, keyword: str) -> Optional[str]:
    """正規化分隔符後用子字串比對找到購物車品項的 item_id"""
    from src.dm import cart_manager

    norm = keyword.replace("·", "").replace(" ", "")
    for item in cart:
        display = cart_manager.format_item(item).replace("·", "").replace(" ", "")
        if norm in display:
            return item.get("item_id")
    return None


# 規則層攔截常數
_EMPTY_CART_MOD_KEYWORDS = ["刪掉", "移除", "撤銷", "取消上一", "刪掉剛剛"]

# last_failed_attempt 中要保留的「客人實際提供的選項」鍵，過濾掉 name/quantity 等內部欄位
_PROVIDED_KEYS = ("rice", "size", "temp", "flavor", "noodle", "customization", "spicy", "extra_egg")
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


class ASRAdapter:
    """ASR 適配器 — 將同步 ASR 方法包裝為異步（webm→ffmpeg→wav→transcribe）"""

    def __init__(self, asr_service):
        self._asr = asr_service

    async def transcribe(self, audio_bytes: bytes) -> str:
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


async def _sse_wrap(stream, label: str):
    """將 orchestrator 的 event stream 包裝為 SSE 格式（全域 try/except 防止靜默斷線）"""
    try:
        async for event in stream:
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error("[SSE-{}] 未捕捉異常: {}", label, e)
        error_data = json.dumps({"message": "伺服器處理錯誤，請再試一次"}, ensure_ascii=False)
        yield f"event: error\ndata: {error_data}\n\n"


# ── 取消意圖偵測（供「模型漏發 [REMOVE] tag」時後端兜底）─────────────────────
# 取消詞刻意收斂：只認終結性取消詞，不認單獨「不要」，
# 避免「飯糰不要辣」「不要香菜」這類加料偏好被誤判成取消品項。
_CANCEL_TRIGGERS = ("不要了", "不用了", "取消", "去掉", "拿掉", "刪掉", "移除", "不需要")
_CANCEL_ALL_KEYWORDS = ("全部", "都不要", "通通", "全不要", "都取消", "整單")


def _item_mentioned_in_text(item: dict, text: str) -> bool:
    """購物車品項是否在這句話被點名（顯示名 + 尾字類別名詞比對）。"""
    from src.dm import cart_manager  # lazy import，對齊本檔既有風格

    display = cart_manager.format_item(item)
    core = display.split("(")[0].strip()  # 去掉杯型/溫度等括號選項
    if not core:
        return False
    if core in text:
        return True
    # 拆掉前綴選項（如「紫米·」）後的片段
    for piece in re.split(r"[·\s]+", core):
        if len(piece) >= 2 and piece in text:
            return True
    # 中文品名核心通常落在尾字（紅茶 / 飯糰 / 蛋餅 / 漢堡）
    for n in (3, 2):
        if len(core) >= n and core[-n:] in text:
            return True
    return False


def _resolve_cancel_intent(text: str, cart: list) -> tuple[bool, list]:
    """偵測『取消品項』意圖並對應到 item_id。

    回傳 (是否整單取消, 要移除的 item_id 清單)；無明確取消意圖回 (False, [])。
    """
    if not cart or not any(kw in text for kw in _CANCEL_TRIGGERS):
        return False, []
    if any(kw in text for kw in _CANCEL_ALL_KEYWORDS):
        return True, []
    matched = [
        item["item_id"]
        for item in cart
        if _item_mentioned_in_text(item, text) and item.get("item_id")
    ]
    return False, matched


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
        session.setdefault("raw_llm_history", [])

        # ── 結帳狀態機攔截：不經 LLM ──
        from src.api.checkout_handler import (  # noqa: E402
            CK_DINE,
            CK_STATES,
            checkout_step,
            patch_last_assistant,
            shortcircuit_reply,
        )

        if session.get("checkout_status") in CK_STATES:
            yielded = False
            async for evt in checkout_step(text, self._session_id, session):
                yielded = True
                yield evt
            if yielded:
                return
            # 反悔出口：checkout_step 已 in-place 清除狀態並回寫，直接 fallthrough

        # ── 規則層攔截（pre-LLM）──
        cart = session.get("cart", [])

        # 1. 空購物車 + 修改意圖
        if not cart and any(kw in text for kw in _EMPTY_CART_MOD_KEYWORDS):
            async for evt in shortcircuit_reply(
                text, "購物車是空的，請先點餐喔！", self._session_id, session, _session_store, cart
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
            async for evt in shortcircuit_reply(
                text, reply, self._session_id, session, _session_store, cart
            ):
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
                tools_schema=[],  # text tag mode：不送 tools，tag 由 done 事件攔截
                tool_map={},  # text tag mode 不走 tool_calls，不需要 tool_map
                allowed_args={},
                context=ctx,
            ):
                evt_type = event.get("type")

                if evt_type == "text_delta":
                    # text tag mode：strip tags 再送 TTS（tags 在 done 事件處理）
                    content = event.get("content", "")
                    content = _ADD_RE.sub("", content)
                    content = _QUERY_RE.sub("", content)
                    content = _REMOVE_RE.sub("", content)
                    content = content.replace(CHECKOUT_TAG, "")
                    content = content.strip()
                    if content:
                        yield {"type": "text_delta", "content": content}

                elif evt_type == "early_tts":
                    yield event  # pass through 給 orchestrator 立即送 TTS

                elif evt_type == "tool_call":
                    tool_trace.append(
                        {"tool_call": event.get("tool_call"), "exec": event.get("exec")}
                    )
                    yield event

                elif evt_type == "done":
                    full_text = event.get("assistant_text", "")
                    # 訓練資料：保存 raw LLM 輸出（含 [ADD:...][QUERY:...] 等 tags，tag strip 前）
                    raw_assistant_text = full_text
                    session["llm_history"] = event.get("history", [])

                    # 推送 monitor 事件 — LLM raw output（含 tag）
                    from src.api.pipeline_event_broadcaster import pipeline_broadcaster

                    pipeline_broadcaster.emit(
                        "llm_raw",
                        self._session_id,
                        {
                            "raw_text": raw_assistant_text,
                            "user_text": text,
                            "usage": event.get("usage", {}),
                        },
                    )

                    if not full_text:
                        full_text = "好的，還需要什麼嗎？"

                    # ── [CHECKOUT] 攔截 ──
                    if CHECKOUT_TAG in full_text:
                        cart = session.get("cart", [])
                        if not cart:
                            full_text = "購物車是空的，請先點餐喔～"
                        else:
                            session["checkout_status"] = CK_DINE
                            full_text = full_text.replace(CHECKOUT_TAG, "")
                        patch_last_assistant(session["llm_history"], full_text)

                    # ── [REMOVE:...] 攔截 ──
                    removed_ok = False
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
                                matched_id = _find_cart_item_id(cart, remove_target)
                                if matched_id:
                                    remove_result = _tool_registry.remove_from_cart(
                                        item_id=matched_id
                                    )
                                else:
                                    remove_result = {
                                        "ok": False,
                                        "message": f"購物車裡沒有{remove_target}",
                                    }

                            removed_ok = remove_result.get("ok", False)
                            full_text = _REMOVE_RE.sub("", full_text).strip()
                            if not full_text:
                                msg_text = remove_result.get("message", "已移除")
                                full_text = f"{msg_text}～還需要什麼？"
                            patch_last_assistant(session["llm_history"], full_text)

                    # ── [SET_QTY:品項|qty=N] 攔截 ──
                    if "[SET_QTY:" in full_text:
                        for sqm in _SET_QTY_RE.finditer(full_text):
                            sq_content = sqm.group(1).strip()
                            sq_parts = sq_content.split("|")
                            sq_target = sq_parts[0].strip()
                            sq_qty = 1
                            if len(sq_parts) > 1 and sq_parts[1].strip().startswith("qty="):
                                try:
                                    sq_qty = int(sq_parts[1].strip().split("=", 1)[1])
                                except ValueError:
                                    pass
                            cart = session.get("cart", [])
                            matched_id = _find_cart_item_id(cart, sq_target)
                            if matched_id:
                                sq_result = _tool_registry.set_item_quantity(
                                    item_id=matched_id, quantity=sq_qty
                                )
                            else:
                                sq_result = {"ok": False, "message": f"購物車裡沒有{sq_target}"}
                            if not sq_result.get("ok"):
                                logger.warning("[SET_QTY] %s", sq_result.get("message"))
                        full_text = _SET_QTY_RE.sub("", full_text).strip()
                        if not full_text:
                            full_text = f"{sq_result.get('message', '已修改')}～還需要什麼？"
                        patch_last_assistant(session["llm_history"], full_text)

                    # ── 取消意圖兜底 ──
                    # 模型漏發 [REMOVE] tag、或發了但 tag 沒對到品項（移除失敗）時，
                    # 依客人取消意圖補移除。沒發 ADD 才兜底；取消詞收斂避免誤刪。
                    if not removed_ok and "[ADD:" not in full_text:
                        cancel_all, cancel_ids = _resolve_cancel_intent(
                            text, session.get("cart", [])
                        )
                        if cancel_all or cancel_ids:
                            if cancel_all:
                                _tool_registry.remove_from_cart(all=True)
                            else:
                                for iid in cancel_ids:
                                    _tool_registry.remove_from_cart(item_id=iid)
                            logger.info("[REMOVE fallback] 模型漏發/誤發 tag，依取消意圖補移除")
                            if not full_text.strip():
                                full_text = "好的，已幫您取消～還需要什麼？"
                                patch_last_assistant(session["llm_history"], full_text)

                    # ── [ADD:品項名|key=value|...] 攔截 ──
                    if "[ADD:" in full_text:
                        add_results: list[dict] = []
                        add_kwargs_list: list[dict] = []
                        last_failed_attempt: Optional[Dict[str, Any]] = None
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
                                    elif key in (
                                        "rice",
                                        "size",
                                        "temp",
                                        "flavor",
                                        "noodle",
                                        "customization",
                                    ):
                                        kwargs[key] = value
                                    elif key in ("spicy", "extra_egg"):
                                        kwargs[key] = value.lower() == "true"
                            add_kwargs_list.append(kwargs)
                            add_result = _tool_registry.add_item(**kwargs)
                            add_results.append(add_result)
                            pipeline_broadcaster.emit(
                                "tool_exec",
                                self._session_id,
                                {
                                    "tool": "add_item",
                                    "input": {k: v for k, v in kwargs.items() if k != "name"}
                                    | {"name": item_name},
                                    "ok": add_result.get("ok", False),
                                    "missing": add_result.get("missing"),
                                    "message": add_result.get("message"),
                                },
                            )
                            if not add_result.get("ok"):
                                logger.warning(
                                    "[ADD tag] 執行失敗: {} → {}",
                                    add_content,
                                    add_result.get("message"),
                                )
                                if add_result.get("missing"):
                                    last_failed_attempt = {
                                        "item_name": item_name,
                                        "missing": add_result["missing"],
                                        "provided": {
                                            k: v for k, v in kwargs.items() if k in _PROVIDED_KEYS
                                        },
                                    }
                        full_text = _ADD_RE.sub("", full_text).strip()

                        # ── 套餐補槽 fallback ──
                        # LLM 忽略 last_failed_attempt context、把回答當獨立品項加了
                        # → 從這一輪 ADD kwargs 撈缺的參數補回去 retry
                        # 必須在 any_ok 清除 session 之前做
                        prev_attempt = session.get("last_failed_attempt")
                        if prev_attempt and not last_failed_attempt:
                            prev_name = prev_attempt["item_name"]
                            already_added = any(
                                r.get("ok") and ak.get("name") == prev_name
                                for r, ak in zip(add_results, add_kwargs_list)
                            )
                            if already_added:
                                session["last_failed_attempt"] = None
                            else:
                                missing = set(prev_attempt.get("missing", []))
                                merged = dict(prev_attempt.get("provided", {}))
                                for ak in add_kwargs_list:
                                    for field in list(missing):
                                        if ak.get(field):
                                            merged[field] = ak[field]
                                            missing.discard(field)
                                if not missing:
                                    retry_kwargs = {"name": prev_name, **merged}
                                    retry_result = _tool_registry.add_item(**retry_kwargs)
                                    if retry_result.get("ok"):
                                        session["last_failed_attempt"] = None
                                        add_results.append(retry_result)
                                        logger.info(
                                            "[ADD fallback] 補槽成功: {} → {}",
                                            retry_kwargs,
                                            retry_result.get("message"),
                                        )

                        # 多輪追問狀態：失敗就記錄、有任何 ADD 成功就清除
                        any_ok = any(r.get("ok") for r in add_results)
                        if last_failed_attempt:
                            session["last_failed_attempt"] = last_failed_attempt
                        elif any_ok:
                            session["last_failed_attempt"] = None

                        # add_item 失敗 → LLM 沒回覆時才補發追問（避免重複）
                        failed = [r for r in add_results if not r.get("ok")]
                        if failed:
                            failed_msgs = [r.get("message", "") for r in failed if r.get("message")]
                            if failed_msgs:
                                followup = "，".join(failed_msgs)
                                if not full_text:
                                    yield {"type": "text_delta", "content": followup}
                                full_text = (full_text + "，" + followup) if full_text else followup

                        # 全成功但 LLM 原文只有 tag（清除後為空）→ 用後端訊息
                        if not full_text and add_results and not failed:
                            ok_msgs = [
                                r.get("message", "") for r in add_results if r.get("message")
                            ]
                            full_text = (
                                "，".join(ok_msgs) + "～還需要什麼？"
                                if ok_msgs
                                else "好的～還需要什麼？"
                            )

                        patch_last_assistant(session["llm_history"], full_text)

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
                        patch_last_assistant(session["llm_history"], full_text)

                    # 訓練資料：append raw LLM pair（user = normalize 後的輸入，assistant = 含 tag 原文）
                    session["raw_llm_history"].append({"role": "user", "content": text})
                    session["raw_llm_history"].append(
                        {"role": "assistant", "content": raw_assistant_text}
                    )

                    _session_store.set(self._session_id, session)

                    # 讀取購物車
                    cart = session.get("cart", [])
                    total_price = cart_manager.calculate_cart_total(cart)

                    # 推送 monitor 事件 — cart 狀態 + 最終回覆給客人
                    pipeline_broadcaster.emit(
                        "session_done",
                        self._session_id,
                        {
                            "cart_summary": [cart_manager.format_item(i) for i in cart],
                            "total_price": total_price,
                            "assistant_text": full_text,
                        },
                    )

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

    # 非同步存原始音訊（不阻塞 event loop）
    audio_path: Path | None = None
    try:
        now = datetime.now()
        audio_dir = _AUDIO_LOG_DIR / now.strftime("%Y-%m-%d")
        audio_dir.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%H%M%S") + f"_{now.microsecond // 1000:03d}"
        audio_path = audio_dir / f"{session_id}_{ts}.webm"
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, audio_path.write_bytes, audio_bytes)
        logger.debug("[VOICE] 音訊已存: {}", audio_path)
    except Exception as e:
        logger.warning("[VOICE] 存音訊失敗: {}", e)
        audio_path = None

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

    asr_adapter = ASRAdapter(_asr_service)
    dm_adapter = StreamingDMAdapter(session_id)
    orchestrator = StreamingOrchestrator(
        asr_adapter, dm_adapter, streaming_tts, session_id=session_id
    )
    return StreamingResponse(
        _sse_wrap(
            orchestrator.process_audio_stream_v2(
                audio_bytes, session_id=session_id, audio_path=audio_path
            ),
            "voice",
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
