# src/api/voice_router.py
from fastapi import APIRouter, UploadFile, File, Depends, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio
import json
import re

from loguru import logger

from src.services.asr_postprocess import postprocess
from src.services.streaming_orchestrator import StreamingOrchestrator
from src.services.tts_implementations import create_tts_model
from src.config.models import TTS_BACKEND
from src.api.auth import get_api_key
from src.api.tag_parser import strip_all_tags

from datetime import datetime
from pathlib import Path

_AUDIO_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "audio"

# 規則層攔截常數
_EMPTY_CART_MOD_KEYWORDS = ["刪掉", "移除", "撤銷", "取消上一", "刪掉剛剛"]
_TOTAL_QUERY_WORDS = ["多少", "幾塊", "幾元"]
# 分類查詢：「有什麼饅頭」「飲料有什麼」— 分類品項多（饅頭 19、飲品 26），
# LLM 憑記憶背誦會整串列出讓 TTS 唸 10-21s。後端直接查菜單報數量 + 代表品項。
# 全句錨定：複合句（「飲料有什麼 我先要一個起司蛋餅」）不匹配，照舊放行給
# LLM 同時發 [QUERY]+[ADD]（b14-01）
_CATEGORY_INQUIRY_RES = (
    re.compile(
        r"^(?:請問)?(?:你們|老闆)?(?:有什麼|有哪些|有那些)(.{1,5}?)(?:口味|種類)?[嗎呢]?[?？]?$"
    ),
    re.compile(
        r"^(?:請問)?(?:你們|老闆)?(.{1,5}?)(?:有什麼|有哪些|有那些)(?:口味|種類)?[嗎呢]?[?？]?$"
    ),
)
# 客人口語 → 菜單分類名。菜單分類名本身不必列，直接對菜單驗證
_CATEGORY_ALIASES = {
    "飲料": "飲品",
    "喝的": "飲品",
    "包子": "饅頭",
}
# 飲品品名帶杯型後綴（有糖豆漿(中)/(大)）— 報代表品項時同品項只算一種
_CUP_SIZE_SUFFIX_RE = re.compile(r"\((?:中|大|小)\)$")
# 品項數 <= 此值直接列全部（只有蔥抓餅），超過改報數量 + 三個代表
_CATEGORY_LIST_ALL_MAX = 4
# 存在性查詢：「你們有賣咖啡嗎」「有沒有蘿蔔糕」— LLM 對品項存在性會謊報
# （菜單有純鮮奶咖啡卻答「沒有賣咖啡」，b10-02）。抽出品項詞交 resolver 驗證，
# 命中才攔截直答；解不了（廁所/聊天詞）fallthrough 給 LLM
_EXISTENCE_QUERY_RE = re.compile(
    r"^(?:請問)?(?:你們|老闆)?(?:有賣|有沒有|有)([一-鿿A-Za-z0-9]{1,10}?)(?:嗎|沒有)?[?？]?$"
)
# 單品詢價：「豬肉蛋漢堡多少錢」— LLM 對單品詢價會腦補價格或謊稱沒賣
# （b9-03/b15-08），resolver 命中直接報價 + 記 pending_offer 接「來一個」
_PRICE_QUERY_RE = re.compile(
    r"^(?:請問)?(?:你們)?(?:一[個份杯顆片]?)?(.{1,12}?)(?:一[個份杯顆片]|一份)?"
    r"(?:要|是)?(?:多少錢|幾塊錢?|幾元|怎麼賣)[?？]?$"
)
# 詢價品項詞若以數量詞開頭（「兩個蛋餅」）→ 非單品詢價，不搶答
_QTY_PREFIX_RE = re.compile(r"^[一二兩三四五六七八九十0-9]+\s*[個份杯顆片]")
# pending_offer 肯定句：「來一份」「好」「要一個」— 上一輪存在性查詢後的
# 純肯定接單句（無品項名），改寫成完整點單交 LLM 走正常 ADD 流程
_OFFER_AFFIRM_RE = re.compile(
    r"^(?:好啊?|要|對|嗯)?[,，\s]*(?:來|給我|幫我來?)?([一兩二三四五六七八九十0-9]+)?(?:份|個|杯|顆|片)?(?:吧|好了|謝謝)?$"
)


def _menu_categories() -> set[str]:
    """菜單分類集合（get_raw_menu 有 module cache，每輪查不多花 I/O）"""
    from src.tools.menu import menu_price_service

    return {i["category"] for i in menu_price_service.get_raw_menu() if i.get("category")}


def _match_category_inquiry(text: str) -> str | None:
    """全句是純分類詢問 → 回菜單分類名，否則 None（交 LLM）"""
    stripped = text.strip()
    for pattern in _CATEGORY_INQUIRY_RES:
        m = pattern.match(stripped)
        if m:
            word = m.group(1).strip()
            category = _CATEGORY_ALIASES.get(word, word)
            return category if category in _menu_categories() else None
    return None


def _build_category_reply(category: str, items: list) -> str:
    """分類查詢回覆：品項少列全部，多則報數量 + 三個代表（TTS 唸得完）"""
    names: list[str] = []
    for item in items:
        if not item.get("available"):
            continue
        name = _CUP_SIZE_SUFFIX_RE.sub("", item["name"])
        if name not in names:
            names.append(name)

    if not names:
        return f"抱歉，{category}今天都賣完了，要不要看看別的？"
    if len(names) <= _CATEGORY_LIST_ALL_MAX:
        return f"我們的{category}有：{'、'.join(names)}，要點哪個？"

    # 代表品項優先取名稱含分類名的：饅頭分類的頭三項是包子（鮮肉包/蔬菜包/
    # 豆沙包），客人問「有什麼饅頭」聽到三種包子會困惑。stable sort 保留菜單
    # 順序；分類名不出現在品名時（飲品/點心）等同不排序
    samples = sorted(names, key=lambda n: category not in n)[:3]
    return f"{category}有{len(names)}種，像是{'、'.join(samples)}，要聽別的嗎？"


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
            CK_STATES,
            CONCRETE_ITEM_WORDS,
            checkout_step,
            shortcircuit_reply,
        )
        from src.api.tag_parser import ADD_RE  # noqa: E402
        from src.api.text_tag_executor import _name_in_text, execute_tags  # noqa: E402
        from src.dm.tool_priming import CHECKOUT_TAG  # noqa: E402

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

        # pending_offer 先 pop（單輪有效）：放最前避免其他規則 shortcircuit
        # 時殘留跨輪
        pending_offer = session.pop("pending_offer", None)

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

        # 2.5 pending_offer 指代橋接：上一輪存在性查詢答「有喔，要來一份嗎？」，
        #     本輪純肯定接單句（「來一份」「好」）無品項名 → 改寫成完整點單
        #     交 LLM 走正常 ADD 流程（槽位追問全復用）
        if pending_offer:
            m_affirm = _OFFER_AFFIRM_RE.match(text.strip())
            if m_affirm and text.strip():
                qty = m_affirm.group(1) or "一"
                text = f"我要{qty}份{pending_offer}"
                logger.info("[OFFER bridge] 肯定句改寫: '{}'", text)

        # 3. 分類查詢強制攔截：後端查菜單直接回，LLM 憑記憶背誦會整串列出
        #    （饅頭 19 項 TTS 唸 10-21s）且會漏品項。複合句放行：查詢+點餐
        #    同句（「飲料有什麼 我先要一個起司蛋餅」）攔截會把點餐部分整句
        #    吞掉（b14-01）→ 全句錨定不匹配，交 LLM 同時發 [QUERY]+[ADD]
        inquiry_category = _match_category_inquiry(text)
        if inquiry_category:
            menu_result = _tool_registry.query_menu(category=inquiry_category)
            if menu_result.get("ok"):
                reply = _build_category_reply(inquiry_category, menu_result.get("items", []))
            else:
                reply = f"抱歉，無法查詢{inquiry_category}菜單，請再試一次。"
            async for evt in shortcircuit_reply(
                text, reply, self._session_id, session, _session_store, cart
            ):
                yield evt
            return

        # 4. 總價查詢兜底：「現在總共多少錢」LLM 會幻覺（空車謊言/載體謊言），
        #    後端直接報 cart total。有品項詞（詢單品價，靜態類別詞 + 全菜單品名
        #    雙閘門）或結帳詞（推進結帳）不攔
        from src.dm.tool_registry import MENU_BASE_NAMES
        from src.tools.order_router import CHECKOUT_KEYWORDS

        if (
            cart
            and any(w in text for w in _TOTAL_QUERY_WORDS)
            and not any(w in text for w in CONCRETE_ITEM_WORDS)
            and not any(w in text for w in CHECKOUT_KEYWORDS)
            and not any(n in text for n in MENU_BASE_NAMES)
        ):
            total = cart_manager.calculate_cart_total(cart)
            if any(cart_manager.is_item_price_pending(i) for i in cart):
                reply = f"目前共{total}元，部分客製品項價格待店員確認，還需要什麼嗎？"
            else:
                reply = f"目前共{total}元，還需要什麼嗎？"
            async for evt in shortcircuit_reply(
                text, reply, self._session_id, session, _session_store, cart
            ):
                yield evt
            return

        # 5. 存在性查詢攔截：「有賣咖啡嗎」抽品項詞交 resolver 驗證，命中直答
        #    （LLM 會謊報「沒賣咖啡」，b10-02）；解不了 fallthrough 給 LLM
        m_exist = _EXISTENCE_QUERY_RE.match(text.strip())
        if m_exist:
            candidate = m_exist.group(1)
            info = _tool_registry._resolve_item_name(candidate)
            if info is not None:
                from src.tools.menu import menu_state_service

                offered = info["resolved_name"]
                if offered in menu_state_service.get_effective_sold_out():
                    reply = f"{offered}今天賣完了，要不要換別的？"
                else:
                    if info.get("category") == "飲品":
                        reply = f"有喔～{offered}，要來一杯嗎？"
                    else:
                        reply = f"有喔～{offered}一份{info['price']}元，要來一份嗎？"
                    session["pending_offer"] = offered
                async for evt in shortcircuit_reply(
                    text, reply, self._session_id, session, _session_store, cart
                ):
                    yield evt
                return

        # 5.5 單品詢價攔截：「豬肉蛋漢堡多少錢」resolver 命中直接報價 +
        #     記 pending_offer（「好 來一個」走橋接）。LLM 對此句型會腦補
        #     價格、謊稱沒賣、或下一輪指代迷失幻覺入車（b9-03/b15-08）
        m_price = _PRICE_QUERY_RE.match(text.strip())
        # 多數量詢價（「兩個蛋餅多少錢」）不搶答：數量詞會被吞進品項名、
        # 口味被 fuzzy 預設成原味 → 後續 offer 橋接把 N 份靜默降成一份。
        # group(1) 以數量詞開頭一律 fallthrough 給 LLM
        if m_price and _QTY_PREFIX_RE.match(m_price.group(1)):
            m_price = None
        if m_price:
            info = _tool_registry._resolve_item_name(m_price.group(1))
            if info is not None:
                from src.tools.menu import menu_state_service

                offered = info["resolved_name"]
                if offered in menu_state_service.get_effective_sold_out():
                    reply = f"{offered}今天賣完了，要不要換別的？"
                else:
                    if info.get("category") == "飲品":
                        from src.tools.menu import menu_price_service

                        p_mid = info["price"]
                        try:
                            p_big = menu_price_service.get_price("飲品", f"{offered}(大)")
                            reply = f"{offered}中杯{p_mid}元、大杯{p_big}元，要來一杯嗎？"
                        except KeyError:
                            reply = f"{offered}一杯{p_mid}元，要來一杯嗎？"
                    else:
                        reply = f"{offered}一份{info['price']}元，要來一份嗎？"
                    session["pending_offer"] = offered
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
        # [CHECKOUT] 輪：LLM 話術會被 execute_tags 取代（確認句/finalize 報號），
        # hold streaming 不逐句送 TTS，done 後由最終話術一次送出
        checkout_turn = False
        # tag-only 輪（LLM 只輸出 tag 無 prose）strip 後無字可 stream，
        # execute_tags 的後端訊息（已移除/已修改/已加入）需在 done 後補送
        streamed_anything = False

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
                    if checkout_turn:
                        continue
                    raw_content = event.get("content", "")
                    # 前提：priming 示範 [CHECKOUT] 恆在句首，tag 前不會有 prose 已先播出
                    if CHECKOUT_TAG in raw_content:
                        checkout_turn = True
                        continue
                    # text tag mode：strip tags 再送 TTS（tags 在 done 事件處理）
                    content = strip_all_tags(raw_content).strip()
                    if content:
                        streamed_anything = True
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

                    # ── 空車謊言重試（no-tag sinkhole）──
                    # 特定句型讓模型掉進「購物車是空的」怪回覆且完全不發 tag
                    # （「三杯中杯冰紅茶 兩個薯餅」6/6 確定性，整單蒸發）。
                    # 觸發限具體品項詞（「我要結帳」這種合法空車句不觸發）；
                    # 重試輸出的每個 ADD 品項名都要在原句有出現才採信，
                    # 擋提醒詞逼出來的幻覺品項入車
                    notag_retried = False
                    if (
                        "[" not in full_text
                        and "購物車" in full_text
                        and "空" in full_text
                        and any(w in text for w in CONCRETE_ITEM_WORDS)
                    ):
                        try:
                            # llm_history 在文字標籤模式（tools_schema=[]）每輪
                            # 固定 append user+assistant 兩條，[:-2] 即本輪之前；
                            # timeout fallback 文案不含「購物車」不會走到這裡
                            retry_messages = _llm_caller._build_messages(
                                SystemPromptBuilder().build(),
                                f"{text}\n（請用 [ADD:品項|參數] 標籤把客人點的品項加入購物車）",
                                session["llm_history"][:-2],
                                context=ctx,
                            )
                            resp = await asyncio.wait_for(
                                _llm_caller.call_llm_async(messages=retry_messages),
                                timeout=15,
                            )
                            retry_content = (
                                resp["choices"][0]["message"].get("content") or ""
                            ).strip()
                            add_names = [
                                c.split("|")[0].strip() for c in ADD_RE.findall(retry_content)
                            ]
                            if add_names and all(_name_in_text(n, text) for n in add_names):
                                logger.info(
                                    "[NO-TAG RETRY] 空車謊言重試成功: {!r} → {!r}",
                                    full_text,
                                    retry_content,
                                )
                                full_text = retry_content
                                notag_retried = True
                            elif add_names:
                                logger.warning(
                                    "[NO-TAG RETRY] 重試 ADD 品項 {} 在原句無佐證，丟棄",
                                    add_names,
                                )
                        except Exception as e:
                            logger.warning("[NO-TAG RETRY] 重試失敗: {}", e)

                    # ── Tag 執行（CHECKOUT / REMOVE / SET_QTY / ADD / QUERY）──
                    tag_result = await execute_tags(full_text, text, session, self._session_id)
                    full_text = tag_result.full_text
                    if checkout_turn or not streamed_anything:
                        # streaming 被 hold（CHECKOUT 輪）或 tag-only 輪無字可 stream
                        # → 最終話術（確認句/finalize 報號/後端訊息）一次送出；
                        # followup 已併入 full_text，不另 yield 避免重複
                        if full_text:
                            yield {"type": "text_delta", "content": full_text}
                    elif notag_retried:
                        # 錯誤 prose 已串流出去，重試結果的話術補送更正
                        if full_text:
                            yield {"type": "text_delta", "content": full_text}
                    elif tag_result.followup_text:
                        yield {"type": "text_delta", "content": tag_result.followup_text}

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

                    # 檢查 finalize_order（tag 同句結帳推進優先；tool_trace 為 tool_calls
                    # 舊路徑，text tag 模式不會命中——若未來重啟 tools 參數需防雙重 finalize）
                    finalize_result = tag_result.finalize_result
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
                        "finalize_result": finalize_result,
                        "preview_result": preview_result,
                    }

        except Exception as e:
            logger.error("[VOICE-STREAM] LLM 不可用，觸發降級: {}", e)
            yield {"type": "fallback", "content": "不好意思，系統暫時無法回應，請再說一次"}
            yield {
                "type": "done",
                "cart": session.get("cart", []),
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
            yield {"event": "done", "data": {"cart": []}}

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
