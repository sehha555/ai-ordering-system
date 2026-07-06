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

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from src.api.checkout_handler import (
    CK_DINE,
    CK_PAY,
    ask_payment_with_total,
    build_checkout_confirm,
    finalize_and_reply,
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
    item_mentioned_in_text,
    find_cart_item_id,
    parse_set_qty_tag,
    resolve_cancel_intent,
)
from src.dm.tool_priming import CHECKOUT_TAG
from src.tools.order_router import CHECKOUT_KEYWORDS


# 「再X一份」增量句：明確 +1，LLM 常把目標總量當增量發 qty>1（見模擬 b4-03 錯單）
_ADD_ONE_MORE_RE = re.compile(r"再(?:加|來|點)?一(?:份|個|杯|顆|片)")

# 槽位屬性腦補檢查：新點單輪（text 點名品項且無修改詞）ADD 帶的屬性值
# 必須在 user text 有字面佐證，否則是 LLM 腦補（「鮪魚飯糰一個」誤帶
# rice=白米 → 錯單），strip 掉讓 add_item 的 missing 機制追問。
# 豁免：修改輪（不要辣/換大杯）與 context 輪（「要辣」沒點名品項）的
# 屬性來自合法記憶；補槽 retry 由 provided merge 補回，不受影響
_SLOT_TEXT_MARKERS = {
    "rice": ("紫", "白", "混"),
    "temp": ("冰", "溫", "熱"),
    "size": ("大", "中", "小"),
}


def _name_in_text(name: str, text: str) -> bool:
    """品項名（或其 2+ 字片段）是否在 user text 被點名"""
    if name in text:
        return True
    for n in (4, 3, 2):
        for i in range(len(name) - n + 1):
            if name[i : i + n] in text:
                return True
    return False


# 修改語意判斷：客人在改既有品項屬性（而非加點新品項）的訊號詞
_MODIFY_WORDS = ("不要", "不加", "改", "換", "去掉")
_ADD_MORE_WORDS = ("再", "還要", "多一", "加一", "另外", "加購", "加點", "也")


def _has_add_more_intent(text: str) -> bool:
    """user text 含加點語意（明確要新的一份，重複 ADD 去重一律讓路）"""
    return any(w in text for w in _ADD_MORE_WORDS)


def _has_modify_intent(text: str) -> bool:
    """user text 含修改語意且無加點語意（供同款重複 ADD 去重判斷）"""
    return any(w in text for w in _MODIFY_WORDS) and not _has_add_more_intent(text)


# 結帳兜底：LLM 漏發 [CHECKOUT] 時依 user text 意圖後端推進。
# 詞表派生自 order_router 單一來源；排除「結案」「沒了」——語意模糊
# （沒了可指售完），silent fallback 需要高精確度
_CHECKOUT_INTENT_WORDS = tuple(w for w in CHECKOUT_KEYWORDS if w not in ("結案", "沒了"))
_CHECKOUT_NEGATE_WORDS = (
    "先不",
    "不用結",
    "不結",
    "不要結",
    "還沒",
    "還不",
    "等一下",
    "等等",
    "晚點",
    "先別",
    "暫時不",
)


def _has_checkout_intent(text: str) -> bool:
    """user text 明確要結帳且無延後/否定語意"""
    return any(w in text for w in _CHECKOUT_INTENT_WORDS) and not any(
        w in text for w in _CHECKOUT_NEGATE_WORDS
    )


def _modify_dedup_key(item: dict) -> Optional[str]:
    """品項基底 key（itemtype+主名稱，不含客製選項）；combo 走專屬去重回 None"""
    t = item.get("itemtype")
    if t == "combo":
        return None
    if t == "carrier":
        name = item.get("menu_name") or f"{item.get('flavor', '')}{item.get('carrier', '')}"
    else:
        name = item.get("flavor") or item.get("drink") or item.get("snack") or item.get("jam_toast")
    return f"{t}:{name}" if name else None


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
    checkout_fallback = False  # 兜底進結帳（LLM 漏發 tag，prose 已 streaming，話術需補送）
    if CHECKOUT_TAG in full_text:
        # 空車但同句帶 [ADD:...]（複合句點餐+結帳）→ 品項即將入車，照常進結帳
        if not cart and "[ADD:" not in full_text:
            full_text = "購物車是空的，請先點餐喔～"
        else:
            session["checkout_status"] = CK_DINE
            checkout_entered = True
            full_text = full_text.replace(CHECKOUT_TAG, "")
        patch_last_assistant(session["llm_history"], full_text)
    elif (cart or "[ADD:" in full_text) and _has_checkout_intent(text):
        # 兜底：客人明說結帳但 LLM 漏發 [CHECKOUT]（機率性 fail，模擬 batch1/2 觀察 4 次）
        session["checkout_status"] = CK_DINE
        checkout_entered = True
        checkout_fallback = True
        logger.info("[CHECKOUT fallback] LLM 漏發 tag，依結帳意圖兜底推進")

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
        retried_ids: set = set()  # 補槽 retry 入車的品項（槽位補完非修改，不參與修改去重）
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
            if _name_in_text(item_name, text) and not any(w in text for w in _MODIFY_WORDS):
                for slot, markers in _SLOT_TEXT_MARKERS.items():
                    if slot in kwargs and not any(m in text for m in markers):
                        logger.info(
                            "[ADD slot-strip] text 無佐證，strip 腦補屬性 {}={}",
                            slot,
                            kwargs[slot],
                        )
                        kwargs.pop(slot)
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
                        retried_ids.add(retry_result.get("item_id"))
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

            # ── 「再X一份」增量修正：text 明說 +1 份，LLM 卻把目標總量當增量 ──
            # 發 ADD qty>1（「蛋餅再加一份」車上已 1 份 → 誤發 qty=2 變 3 份）。
            # 只在本輪成功 ADD 恰 1 個時修正，避免波及多品項句的其他數量
            ok_results = [r for r in add_results if r.get("ok") and r.get("item_id")]
            if len(ok_results) == 1 and _ADD_ONE_MORE_RE.search(text):
                added = next(
                    (i for i in cart if i.get("item_id") == ok_results[0]["item_id"]), None
                )
                if added and int(added.get("quantity", 1) or 1) > 1:
                    logger.info(
                        "[ADD qty-fix] 「再X一份」qty {}→1 ({})",
                        added.get("quantity"),
                        added.get("item_id"),
                    )
                    added["quantity"] = 1

            # ── 修改去重：客人改屬性 LLM 誤發新 ADD → 同款舊品項移除 ──
            # 觸發（皆需無加點語意 + 同款新舊各恰 1 個）：
            #   (a) text 含修改詞（不要辣/換白米）
            #   (b) text 沒點名該品項（如追問「要加辣菜脯嗎」答「要辣」）——
            #       客人沒說品項名，LLM 是從 context 撈的，必為修改非新點單
            # 舊品項只限「上一輪剛成功 ADD 的」——修改語意天然接在剛點完的下一句，
            # 更早輪的同款是別筆訂單（多人合點），不可誤刪。
            # 補槽 retry 品項排除：槽位補答（如「換紫米的」）是完成前輪加點，非修改既有品項
            modify_new_ids = this_turn_ids - retried_ids
            if not _has_add_more_intent(text):
                has_modify_words = any(w in text for w in _MODIFY_WORDS)
                prev_turn_add_ids = set(session.get("last_turn_add_ids", []))
                by_key: dict[str, list] = {}
                for item in cart:
                    key = _modify_dedup_key(item)
                    if key is not None:
                        by_key.setdefault(key, []).append(item)
                for items in by_key.values():
                    new_items = [i for i in items if i.get("item_id") in modify_new_ids]
                    old_items = [
                        i
                        for i in items
                        if i.get("item_id") not in this_turn_ids
                        and i.get("item_id") in prev_turn_add_ids
                    ]
                    if (
                        len(new_items) == 1
                        and len(old_items) == 1
                        and (has_modify_words or not item_mentioned_in_text(new_items[0], text))
                    ):
                        cart.remove(old_items[0])
                        logger.info(
                            "[ADD modify-dedup] 修改語意移除舊品項 {} (保留本輪 {})",
                            old_items[0].get("item_id"),
                            new_items[0].get("item_id"),
                        )

            # ── 結帳複述去重：[CHECKOUT] 輪把已在車上的品項重 ADD → 移除新的 ──
            # 結帳句常複述整單（「蘿蔔糕一份跟奶茶 結帳」），複述品項沒有新資訊；
            # qty>1 是明確改量/加點意圖，不去重。獨立於修改去重判斷（不巢狀在
            # 加點詞閘門內，「我也要結帳」的「也」不應使複述去重失效）
            if checkout_entered and not _has_add_more_intent(text):
                for new_item in [i for i in cart if i.get("item_id") in modify_new_ids]:
                    key = _modify_dedup_key(new_item)
                    if key is None or int(new_item.get("quantity", 1) or 1) > 1:
                        continue
                    has_older = any(
                        _modify_dedup_key(i) == key
                        for i in cart
                        if i.get("item_id") not in this_turn_ids
                    )
                    if has_older:
                        cart.remove(new_item)
                        logger.info(
                            "[ADD checkout-dedup] 結帳複述移除重複品項 {}",
                            new_item.get("item_id"),
                        )

            # 供下一輪修改去重辨識「上一輪剛加的品項」
            session["last_turn_add_ids"] = list(this_turn_ids)

        # add_item 失敗 → 追問一律補發：LLM prose（已 streaming）不含後端追問，
        # 不設 followup_text 客人會聽不到「缺什麼」死等（voice_router 對
        # not streamed_anything 輪改 yield full_text，該路徑不會重複）
        failed = [r for r in add_results if not r.get("ok")]
        if failed:
            failed_msgs = [r.get("message", "") for r in failed if r.get("message")]
            if failed_msgs:
                followup = "，".join(failed_msgs)
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
    finalize_result = None
    if checkout_entered and session.get("last_failed_attempt"):
        # ADD 補槽失敗：撤回結帳狀態讓缺欄位追問先走，
        # 否則下輪補槽回答（如「紫米」）會被結帳狀態機吃掉造成死路
        session.pop("checkout_status", None)
        session.pop("checkout_dine_type", None)
    elif checkout_entered:
        dine = parse_dine_type(text)
        cart = session.get("cart", [])
        if not cart:
            # 空車放行進結帳但 ADD 最終未入車（如品項不存在）→ 撤回結帳狀態
            session.pop("checkout_status", None)
        elif dine:
            from src.dm import cart_manager  # noqa: PLC0415

            # 有客製待確認 → 不能先付走 pending；否則同句有付款就直接 finalize
            pay = "pending" if cart_manager.cart_has_pending(cart) else parse_payment(text)
            if pay:
                full_text, finalize_result = finalize_and_reply(dine, pay, session, _tool_registry)
            else:
                # 同句帶內用外帶沒經過確認句 → 問付款時帶總金額
                session["checkout_dine_type"] = dine
                session["checkout_status"] = CK_PAY
                full_text = ask_payment_with_total(cart)
            logger.info(
                "[CHECKOUT 同句推進] dine={} finalize={}", dine, finalize_result is not None
            )
            patch_last_assistant(session["llm_history"], full_text)
            if checkout_fallback:
                # 兜底輪 LLM prose 已 streaming（無 tag 可 hold），推進話術經 followup 補送
                followup_text = full_text
        else:
            # 第一問：後端組品項+總金額確認句，取代 LLM 話術（金額不靠 LLM 保證正確）
            full_text = build_checkout_confirm(cart)
            patch_last_assistant(session["llm_history"], full_text)
            if checkout_fallback:
                followup_text = full_text

    return TagExecutionResult(
        full_text=full_text,
        followup_text=followup_text,
        finalize_result=finalize_result,
    )
