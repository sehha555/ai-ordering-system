# src/api/checkout_handler.py
# 結帳狀態機：從 voice_router.py 抽出的純結帳邏輯
# noqa: E402

from loguru import logger

# ── 結帳狀態機常數 ──
CK_DINE = "CHECKOUT_DINE"
CK_PAY = "CHECKOUT_PAY"
CK_STATES = (CK_DINE, CK_PAY)

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


def parse_dine_type(text: str) -> str | None:
    """解析內用/外帶關鍵字，回傳 'dine-in'、'take-out' 或 None"""
    t = text.strip()
    if any(kw in t for kw in ["內用", "這裡吃", "在這吃", "在這裡", "dine"]):
        return "dine-in"
    if any(kw in t for kw in ["外帶", "帶走", "打包", "take"]):
        return "take-out"
    return None


def parse_payment(text: str) -> str | None:
    """解析付款方式關鍵字，回傳 'cash'、'line_pay' 或 None"""
    t = text.strip()
    if any(kw in t for kw in ["現金", "cash"]):
        return "cash"
    if any(kw in t for kw in ["Line", "line", "行動", "支付", "pay", "Pay", "LINE"]):
        return "line_pay"
    return None


def has_order_intent(text: str) -> bool:
    """檢查 text 是否包含點餐意圖關鍵字"""
    return any(kw in text for kw in _ORDER_INTENT_KEYWORDS)


def patch_last_assistant(history: list[dict], content: str) -> None:
    """覆寫 history 中最後一條 assistant 回覆"""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            msg["content"] = content
            return


def exit_checkout(session_id: str, session: dict, session_store) -> None:
    """清除結帳狀態並回寫 session（反悔出口用）"""
    session.pop("checkout_status", None)
    session.pop("checkout_dine_type", None)
    session_store.set(session_id, session)


async def shortcircuit_reply(
    text: str, reply: str, session_id: str, session: dict, session_store, cart: list
):
    """規則層攔截共用：寫入 history、回寫 session、yield text_delta + done。"""
    from src.dm import cart_manager

    session["llm_history"].append({"role": "user", "content": text})
    session["llm_history"].append({"role": "assistant", "content": reply})
    session_store.set(session_id, session)
    yield {"type": "text_delta", "content": reply}
    yield {
        "type": "done",
        "cart": cart,
        "order_payload": {"total_price": cart_manager.calculate_cart_total(cart)},
        "finalize_result": None,
        "preview_result": None,
    }


async def checkout_step(text: str, session_id: str, session: dict):
    """結帳狀態機：根據 checkout_status 處理 user input，不經 LLM。
    未 yield 任何事件 = 反悔退出，caller 應 fallthrough 到 LLM。
    """
    from src.services import container
    from src.dm import cart_manager

    _session_store = container.session_store
    _tool_registry = container.tool_registry
    _tool_registry.set_session_id(session_id)

    status = session.get("checkout_status")

    finalize_result = None

    if status == CK_DINE:
        dine = parse_dine_type(text)
        if dine:
            session["checkout_dine_type"] = dine
            cart = session.get("cart", [])
            if cart_manager.cart_has_pending(cart):
                # 有客製待確認 → 不能先付：跳過付款步驟，直接建「待店員結算」單
                result = _tool_registry.finalize_order(dine_type=dine, payment_method="pending")
                session.pop("checkout_status", None)
                session.pop("checkout_dine_type", None)
                if result.get("ok"):
                    finalize_result = result
                    order_number = result.get("order_number", "")
                    reply = (
                        f"好的，{order_number}號～有客製品項需店員確認價格，"
                        "請稍候結算，這邊先不收款喔。"
                    )
                else:
                    reply = result.get("message", "結帳失敗，請再試一次")
            else:
                session["checkout_status"] = CK_PAY
                reply = "現金還是行動支付？"
        elif has_order_intent(text):
            # 反悔：intent 檢查必須在 parse 失敗後才執行
            exit_checkout(session_id, session, _session_store)
            return
        else:
            reply = "請問是內用還是外帶？"

    elif status == CK_PAY:
        pay = parse_payment(text)
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
        elif has_order_intent(text):
            # 反悔：intent 檢查必須在 parse 失敗後才執行
            exit_checkout(session_id, session, _session_store)
            return
        else:
            reply = "請問要現金還是行動支付？"

    # 追加對話歷史
    session["llm_history"].append({"role": "user", "content": text})
    session["llm_history"].append({"role": "assistant", "content": reply})
    _session_store.set(session_id, session)

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
