# src/api/text_tag_executor.py
"""LLM 回覆的 text tag 執行器

從 voice_router.py done 事件抽出，負責：
- [CHECKOUT] 攔截
- [REMOVE:...] 攔截
- [SET_QTY:...] 攔截
- 取消意圖兜底
- [ADD:...] 攔截（含套餐補槽 fallback）
- [QUERY:...] 攔截
- add_item 失敗的 followup 訊息
- 全成功但 LLM 原文為空的 fallback
- patch_last_assistant
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from src.api.checkout_handler import (
    CK_DINE,
    CK_PAY,
    parse_dine_type,
    parse_payment,
    patch_last_assistant,
)
from src.api.tag_parser import (
    ADD_RE,
    PROVIDED_KEYS,
    QUERY_RE,
    REMOVE_RE,
    SET_QTY_RE,
    find_cart_item_id,
    parse_set_qty_tag,
    resolve_cancel_intent,
)
from src.dm.tool_priming import CHECKOUT_TAG


@dataclass
class TagExecutionResult:
    """tag 執行後的統一回傳結構"""

    full_text: str  # 處理後準備送 TTS 的最終回覆文字
    followup_text: str = ""  # 需要額外 yield 的 text_delta（失敗追問）
    finalize_result: Optional[dict] = None  # 同句結帳推進直接 finalize 的結果


async def execute_tags(
    full_text: str,
    text: str,  # 使用者原始輸入（用於取消意圖偵測）
    session: dict,
    session_id: str,
) -> TagExecutionResult:
    """處理 LLM 回覆中的 text tags，回傳 TagExecutionResult。

    session 會被 in-place 修改（cart/last_failed_attempt 等），
    呼叫方需在此函式回傳後自行呼叫 session_store.set() 儲存。
    """
    from src.services import container
    from src.api.pipeline_event_broadcaster import pipeline_broadcaster

    _tool_registry = container.tool_registry
    _tool_registry.set_session_id(session_id)

    followup_text = ""
    add_results: List[dict] = []
    cart = session.get("cart", [])

    # ── [CHECKOUT] 攔截 ──
    checkout_entered = False  # 本輪剛進結帳狀態（供尾端同句推進判斷）
    if CHECKOUT_TAG in full_text:
        # 空車但同句帶 [ADD:...]（複合句點餐+結帳）→ 品項即將入車，照常進結帳
        if not cart and "[ADD:" not in full_text:
            full_text = "購物車是空的，請先點餐喔～"
        else:
            session["checkout_status"] = CK_DINE
            checkout_entered = True
            full_text = full_text.replace(CHECKOUT_TAG, "")
        patch_last_assistant(session["llm_history"], full_text)

    # ── [REMOVE:...] 攔截 ──
    removed_ok = False
    if "[REMOVE:" in full_text:
        remove_match = REMOVE_RE.search(full_text)
        if remove_match:
            remove_target = remove_match.group(1).strip()
            remove_result: dict = {"ok": False, "message": "移除失敗"}

            if remove_target == "all":
                remove_result = _tool_registry.remove_from_cart(all=True)
            elif remove_target == "last":
                remove_result = _tool_registry.remove_from_cart(last=True)
            else:
                matched_id = find_cart_item_id(cart, remove_target)
                if matched_id:
                    remove_result = _tool_registry.remove_from_cart(item_id=matched_id)
                else:
                    remove_result = {
                        "ok": False,
                        "message": f"購物車裡沒有{remove_target}",
                    }

            removed_ok = remove_result.get("ok", False)
            if removed_ok:
                cart = session.get("cart", [])
            full_text = REMOVE_RE.sub("", full_text).strip()
            if not full_text:
                msg_text = remove_result.get("message", "已移除")
                full_text = f"{msg_text}～還需要什麼？"
            patch_last_assistant(session["llm_history"], full_text)

    # ── [SET_QTY:品項|qty=N] 攔截 ──
    sq_result: dict = {"ok": False, "message": "已修改"}
    if "[SET_QTY:" in full_text:
        for sqm in SET_QTY_RE.finditer(full_text):
            sq_target, sq_qty = parse_set_qty_tag(sqm.group(1).strip())
            matched_id = find_cart_item_id(cart, sq_target)
            if matched_id:
                sq_result = _tool_registry.set_item_quantity(item_id=matched_id, quantity=sq_qty)
            else:
                sq_result = {"ok": False, "message": f"購物車裡沒有{sq_target}"}
            if not sq_result.get("ok"):
                logger.warning("[SET_QTY] %s", sq_result.get("message"))
        full_text = SET_QTY_RE.sub("", full_text).strip()
        if not full_text:
            full_text = f"{sq_result.get('message', '已修改')}～還需要什麼？"
        patch_last_assistant(session["llm_history"], full_text)

    # ── 取消意圖兜底 ──
    # 模型漏發 [REMOVE] tag、或發了但 tag 沒對到品項（移除失敗）時，
    # 依客人取消意圖補移除。沒發 ADD 才兜底；取消詞收斂避免誤刪。
    if not removed_ok and "[ADD:" not in full_text:
        cancel_all, cancel_ids = resolve_cancel_intent(text, cart)
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
        add_kwargs_list: List[Dict[str, Any]] = []
        last_failed_attempt: Optional[Dict[str, Any]] = None
        for add_content in ADD_RE.findall(full_text):
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
                    elif key in ("rice", "size", "temp", "flavor", "noodle", "customization"):
                        kwargs[key] = value
                    elif key in ("spicy", "extra_egg"):
                        kwargs[key] = value.lower() == "true"
            add_kwargs_list.append(kwargs)
            add_result = _tool_registry.add_item(**kwargs)
            add_results.append(add_result)
            pipeline_broadcaster.emit(
                "tool_exec",
                session_id,
                {
                    "tool": "add_item",
                    "input": {k: v for k, v in kwargs.items() if k != "name"} | {"name": item_name},
                    "ok": add_result.get("ok", False),
                    "missing": add_result.get("missing"),
                    "message": add_result.get("message"),
                },
            )
            if not add_result.get("ok"):
                logger.warning(
                    "[ADD tag] 執行失敗: {} → {}", add_content, add_result.get("message")
                )
                if add_result.get("missing"):
                    last_failed_attempt = {
                        "item_name": item_name,
                        "missing": add_result["missing"],
                        "provided": {k: v for k, v in kwargs.items() if k in PROVIDED_KEYS},
                    }
        full_text = ADD_RE.sub("", full_text).strip()

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
                    for f in missing.copy():
                        if ak.get(f):
                            merged[f] = ak[f]
                            missing.discard(f)
                    if not missing:
                        break
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

        # ── 套餐去重：LLM 修改溫度時重複 ADD 相同套餐 → 保留新的、移除舊的 ──
        if any_ok:
            this_turn_ids = {r["item_id"] for r in add_results if r.get("ok") and r.get("item_id")}
            cart = session.get("cart", [])
            combo_by_name: dict[str, list] = {}
            for item in cart:
                if item.get("itemtype") == "combo":
                    combo_by_name.setdefault(item["combo_name"], []).append(item)
            for cn, items in combo_by_name.items():
                if len(items) < 2:
                    continue
                new_items = [i for i in items if i["item_id"] in this_turn_ids]
                old_items = [i for i in items if i["item_id"] not in this_turn_ids]
                if new_items and old_items:
                    for old in old_items:
                        cart.remove(old)
                    logger.info(
                        "[ADD dedup] 移除舊套餐 {} (保留本輪 {})",
                        [o["item_id"] for o in old_items],
                        [n["item_id"] for n in new_items],
                    )

        # add_item 失敗 → LLM 沒回覆時才補發追問（避免重複）
        failed = [r for r in add_results if not r.get("ok")]
        if failed:
            failed_msgs = [r.get("message", "") for r in failed if r.get("message")]
            if failed_msgs:
                followup = "，".join(failed_msgs)
                if not full_text:
                    followup_text = followup
                full_text = (full_text + "，" + followup) if full_text else followup

        # 全成功但 LLM 原文只有 tag（清除後為空）→ 用後端訊息
        if not full_text and add_results and not failed:
            ok_msgs = [r.get("message", "") for r in add_results if r.get("message")]
            full_text = "，".join(ok_msgs) + "～還需要什麼？" if ok_msgs else "好的～還需要什麼？"

        patch_last_assistant(session["llm_history"], full_text)

    # ── [QUERY:分類] 攔截 ──
    if "[QUERY" in full_text:
        query_match = QUERY_RE.search(full_text)
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
        full_text = QUERY_RE.sub("", full_text).strip()
        patch_last_assistant(session["llm_history"], full_text)

    # ── 複合單句結帳推進：同句已帶內用外帶（/付款）→ 直接推進狀態機 ──
    # 放在 [ADD:...] 執行之後，確保同句加點的品項已入 cart 才 finalize。
    # 有補槽失敗（last_failed_attempt）時不推進，讓缺欄位追問先走。
    finalize_result = None
    if checkout_entered and not session.get("last_failed_attempt"):
        dine = parse_dine_type(text)
        cart = session.get("cart", [])
        if dine and cart:
            from src.dm import cart_manager  # noqa: PLC0415

            if cart_manager.cart_has_pending(cart):
                # 有客製待確認 → 不能先付，直接建「待店員結算」單（同 checkout_step）
                result = _tool_registry.finalize_order(dine_type=dine, payment_method="pending")
                session.pop("checkout_status", None)
                if result.get("ok"):
                    finalize_result = result
                    order_number = result.get("order_number", "")
                    full_text = (
                        f"好的，{order_number}號～有客製品項需店員確認價格，"
                        "請稍候結算，這邊先不收款喔。"
                    )
                else:
                    full_text = result.get("message", "結帳失敗，請再試一次")
            else:
                pay = parse_payment(text)
                if pay:
                    result = _tool_registry.finalize_order(dine_type=dine, payment_method=pay)
                    session.pop("checkout_status", None)
                    if result.get("ok"):
                        finalize_result = result
                        full_text = f"好，{result.get('order_number', '')}號～"
                    else:
                        full_text = result.get("message", "結帳失敗，請再試一次")
                else:
                    session["checkout_dine_type"] = dine
                    session["checkout_status"] = CK_PAY
                    full_text = "現金還是行動支付？"
            logger.info(
                "[CHECKOUT 同句推進] dine={} finalize={}", dine, finalize_result is not None
            )
            patch_last_assistant(session["llm_history"], full_text)

    return TagExecutionResult(
        full_text=full_text,
        followup_text=followup_text,
        finalize_result=finalize_result,
    )
