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
    "noodle": ("油麵", "烏龍"),
}

# 需 text 佐證的槽（slot-strip / retry-strip 共用）：marker 槽 + 自由值的 flavor
_EVIDENCED_SLOTS = (*_SLOT_TEXT_MARKERS, "flavor")

# 鐵板麵口味選項詞（flavor 值域依品項而異，唯一的選項型追問是鐵板麵四口味；
# 開放型追問「什麼口味」以「口味」一詞判斷，見 _prose_asks_slot）
_FLAVOR_OPTION_MARKERS = ("黑椒", "蘑菇", "義大利", "咖哩")


def _name_in_text(name: str, text: str) -> bool:
    """品項名（或其 2+ 字片段、套餐俗稱）是否在 user text 被點名。

    套餐必查別名：LLM 發正規名（套餐一）而客人說俗稱（一號餐），
    滑窗對不上會被誤判成 context 輪、腦補屬性逃過 slot-strip 入車錯單
    """
    if name in text:
        return True
    from src.dm.tool_registry import COMBO_NUMBER_ALIASES  # noqa: PLC0415

    for alias, canonical in COMBO_NUMBER_ALIASES.items():
        if canonical == name and alias in text:
            return True
    for n in (4, 3, 2):
        for i in range(len(name) - n + 1):
            if name[i : i + n] in text:
                return True
    return False


# 補槽值佐證的否定詞：「不要黑椒」不算 flavor=黑椒 的佐證。
# 單字否定（不/免/無）配合前窗 contains 檢查，抓「不加辣」「不要加辣」
# 這類否定詞與片段不緊鄰或重疊的形態
_VALUE_NEG_PREFIXES = ("不要", "不加", "去掉", "不用", "別", "不", "免", "無")

# 前窗掃描遇標點/空白截斷（「不用等，加辣」的「加辣」不受前句否定詞波及）
_WINDOW_BREAKS = "，。？！、 ,?!"


def _frag_affirmed(frag: str, text: str) -> bool:
    """片段是否以非否定語境出現在 user text：任一出現處往前 4 字窗
    （遇標點截斷）不含否定詞才算數（「蛋餅不要加辣」的「辣」前窗含
    「不要」→ 不算 加辣 的佐證）"""
    start = 0
    while True:
        idx = text.find(frag, start)
        if idx == -1:
            return False
        window = text[max(0, idx - 4) : idx]
        for p in _WINDOW_BREAKS:
            if p in window:
                window = window.rsplit(p, 1)[-1]
        if not any(neg in window for neg in _VALUE_NEG_PREFIXES):
            return True
        start = idx + 1


def _value_in_text_affirmed(value: str, text: str) -> bool:
    """槽值（前兩字）是否以非否定語境出現在 user text（自由值槽的腦補佐證）"""
    return _frag_affirmed(value[:2], text)


# customization 值的功能字/量詞（去除後剩內容核心字：「加辣菜脯」→ 辣菜脯）。
# 客製是自由文字（含否定型/未定價修飾），字面表是取捨；若客製詞彙未來收斂，
# 更深做法是從菜單 config（addon_prices/recipes）derive allowlist
_CUST_FUNC_CHARS = "加要不去掉免多少半個一的"


# 客製值的否定形式開頭字（去冰/不加蔥/少糖/免蔥/無糖）
_NEG_VALUE_HEADS = "不去免無少"


def _customization_evidenced(value: str, text: str) -> bool:
    """customization 值在 user text 有佐證。客製一定當輪說出口（temp/rice
    可來自合法跨輪記憶，客製沒有這種場景），無佐證即 LLM 腦補。
    判準：值開頭以非否定語境直接出現（加辣/去冰 — LLM 照抄客人原話，
    「不要加辣」前窗含否定不算）；或內容核心字有佐證 — 值為肯定形式（加X）
    核心字須非否定出現（「不要辣」不佐證 加辣），值為否定形式（去冰/不加蔥）
    核心字任意出現即可（客人的否定說法「不要冰」與 LLM 正規化詞「去冰」
    常不同，否定語境恰是佐證）"""
    if value[:2] and _frag_affirmed(value[:2], text):
        return True
    core = [c for c in value if c not in _CUST_FUNC_CHARS]
    if value[:1] in _NEG_VALUE_HEADS:
        return any(c in text for c in core)
    return any(_frag_affirmed(c, text) for c in core)


def _slot_evidenced(slot: str, value: str, text: str) -> bool:
    """該槽的 ADD 屬性值在 user text 有佐證（slot-strip / retry-strip 共用）。
    noodle 二選一互斥：類別詞命中不足以佐證值本身（句含「油麵」也會放行
    幻覺的 noodle=烏龍麵）→ 與無 marker 槽同走值精確比對。
    flavor 加查別名表：客人講俗稱/全稱（黑胡椒/香菇）、LLM 正規化成菜單
    短稱（黑椒/蘑菇），裸字面比對會誤殺合法口味造成重複追問"""
    markers = None if slot == "noodle" else _SLOT_TEXT_MARKERS.get(slot)
    if markers:
        return any(m in text for m in markers)
    if _value_in_text_affirmed(value, text):
        return True
    if slot == "flavor":
        from src.dm.tool_registry import _IRON_NOODLE_FLAVOR_CANON  # noqa: PLC0415

        return any(
            (canon.startswith(value) or value.startswith(canon)) and _frag_affirmed(alias, text)
            for alias, canon in _IRON_NOODLE_FLAVOR_CANON.items()
        )
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


def _prose_asks_slot(prose: str, slot: str) -> bool:
    """prose 是否已在追問該槽（呼叫方需先確認 prose 帶問號）。
    判準：該 slot 兩個選項詞在同一子句以「還是/或」相連（「冰的還是溫的」），
    防常用字假陽性（「大概中午」含 大+中 但非追問）。
    flavor 開放型追問（「饅頭要什麼口味？」）以「口味」判斷，且必須與問號
    同子句 —「招牌口味喔！」這種非疑問語境不算已問，誤判會吞掉追問致死等。"""
    if slot == "flavor" and re.search(r"口味[^，。？?!！]*[？?]", prose):
        return True
    markers = _FLAVOR_OPTION_MARKERS if slot == "flavor" else _SLOT_TEXT_MARKERS.get(slot, ())
    return any(
        re.search(f"{a}[^，。？?!！]*?(?:還是|或)[^，。？?!！]*?{b}", prose)
        for a in markers
        for b in markers
        if a != b
    )


def _pending_checkout_reply(attempt: dict) -> str:
    """結帳遇 pending 補槽 → 重放追問（槽位補齊後由 pending_checkout 接回結帳）"""
    question = attempt.get("message") or f"{attempt.get('item_name', '品項')}的選項還沒選好喔"
    return f"好的～先跟您確認：{question}"


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
    add_kwargs_list: List[Dict[str, Any]] = []
    cart = session.get("cart", [])
    # 上輪結帳被補槽追問擋下的接續 flag：補槽期間每輪由尾端收斂點延續，
    # attempt 解除當輪接回結帳或（客人改口/否定結帳）丟棄；
    # attempt 品項名先 snapshot（本輪補槽成功會清掉 attempt）
    pending_checkout = session.pop("pending_checkout", False)
    pending_item_name = (session.get("last_failed_attempt") or {}).get("item_name")

    # ── [CHECKOUT] 攔截 ──
    # 追問鏈中結帳（last_failed_attempt 非空）也照常放行進結帳，
    # 統一由尾端撤回塊重放追問 + 記 pending flag（模擬 E 族：整單蒸發）
    checkout_entered = False  # 本輪剛進結帳狀態（供尾端同句推進判斷）
    checkout_fallback = False  # 兜底進結帳（LLM 漏發 tag，prose 已 streaming，話術需補送）
    if CHECKOUT_TAG in full_text:
        # 空車但同句帶 [ADD:...]（複合句點餐+結帳）→ 品項即將入車，照常進結帳
        if not cart and "[ADD:" not in full_text and not session.get("last_failed_attempt"):
            full_text = "購物車是空的，請先點餐喔～"
        else:
            session["checkout_status"] = CK_DINE
            checkout_entered = True
            full_text = full_text.replace(CHECKOUT_TAG, "")
        patch_last_assistant(session["llm_history"], full_text)
    elif (
        cart or "[ADD:" in full_text or session.get("last_failed_attempt")
    ) and _has_checkout_intent(text):
        # 兜底：客人明說結帳但 LLM 漏發 [CHECKOUT]（機率性 fail，模擬 batch1/2 觀察 4 次）
        session["checkout_status"] = CK_DINE
        checkout_entered = True
        checkout_fallback = True
        logger.info("[CHECKOUT fallback] LLM 漏發 tag，依結帳意圖兜底推進")

    # ── [REMOVE:...] 攔截 ──
    removed_ok = False
    removed_item_snapshot: Optional[Dict[str, Any]] = None  # 同輪換品項的數量/屬性繼承用
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
                    removed_item_snapshot = next(
                        (i for i in cart if i.get("item_id") == matched_id), None
                    )
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

    # ── [SET_QTY:品項|qty=N|size=…|temp=…] 攔截 ──
    # LLM 表達「換大杯/改溫的」慣性發 SET_QTY 帶 size/temp（不照 demo 的
    # REMOVE+ADD），attrs 走 set_item_attrs；qty 沒給就不動數量
    sq_result: dict = {"ok": False, "message": "已修改"}
    if "[SET_QTY:" in full_text:
        for sqm in SET_QTY_RE.finditer(full_text):
            sq_target, sq_qty, sq_attrs = parse_set_qty_tag(sqm.group(1).strip())
            matched_id = find_cart_item_id(cart, sq_target)
            if not matched_id:
                sq_result = {"ok": False, "message": f"購物車裡沒有{sq_target}"}
            else:
                if sq_qty is not None:
                    sq_result = _tool_registry.set_item_quantity(
                        item_id=matched_id, quantity=sq_qty
                    )
                if sq_attrs:
                    sq_result = _tool_registry.set_item_attrs(item_id=matched_id, **sq_attrs)
                if sq_qty is None and not sq_attrs:
                    # 純 [SET_QTY:品項] 無參數：維持舊行為（數量設 1）
                    sq_result = _tool_registry.set_item_quantity(item_id=matched_id, quantity=1)
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
                # flavor 不在 markers 表（值域自由），經 _slot_evidenced 走值比對
                # （b8-02「套餐七 冰的 油麵」腦補 flavor=咖哩 入車）
                for slot in _EVIDENCED_SLOTS:
                    if slot in kwargs and not _slot_evidenced(slot, str(kwargs[slot]), text):
                        logger.info(
                            "[ADD slot-strip] text 無佐證，strip 腦補屬性 {}={}",
                            slot,
                            kwargs[slot],
                        )
                        kwargs.pop(slot)
            # ── 補槽輪腦補防護 ──
            # context 輪（text 沒點名品項）原本豁免 strip：補槽回答不會複述品名。
            # 但 LLM 會順手腦補沒被問到的槽（「烏龍麵 冰的」→ flavor=黑椒 出錯餐）。
            # 這輪若正是同品項的補槽 retry → 逐槽檢查：本輪 text 有佐證、
            # 或前幾輪客人已提供（prev.provided）才保留，其餘 strip 掉重新追問
            prev_slot_attempt = session.get("last_failed_attempt")
            if (
                prev_slot_attempt
                and prev_slot_attempt.get("item_name") == item_name
                and not _name_in_text(item_name, text)
            ):
                provided = prev_slot_attempt.get("provided", {})
                for slot in _EVIDENCED_SLOTS:
                    if slot not in kwargs or provided.get(slot):
                        continue
                    if not _slot_evidenced(slot, str(kwargs[slot]), text):
                        logger.info(
                            "[ADD retry-strip] 補槽輪腦補 {}={} 無佐證，strip",
                            slot,
                            kwargs[slot],
                        )
                        kwargs.pop(slot)
            # ── customization 腦補防護（不限輪次）──
            # 槽位有「合法跨輪記憶」豁免（context 輪的 temp 來自前輪問答），
            # 客製沒有 — 一定當輪說出口。無 text 佐證即腦補（priming demo 的
            # 加辣菜脯被無中生有帶入 → 錯單出貨，b8-06/b8-10/b7-01）。
            # 唯一合法跨輪來源：同品項補槽 retry 前幾輪已提供（prev.provided）
            prev_provided_cust = (
                prev_slot_attempt
                and prev_slot_attempt.get("item_name") == item_name
                and prev_slot_attempt.get("provided", {}).get("customization")
            )
            if (
                "customization" in kwargs
                and not prev_provided_cust
                and not _customization_evidenced(str(kwargs["customization"]), text)
            ):
                logger.info(
                    "[ADD cust-strip] text 無佐證，strip 腦補客製 {}",
                    kwargs["customization"],
                )
                kwargs.pop("customization")
            # ── 換杯型/屬性的 REMOVE+ADD 繼承 ──
            # 「三杯紅茶換大杯」LLM 走 demo 的 REMOVE+ADD：REMOVE 殺掉 x3、
            # ADD 重建 x1，數量與沒複述的屬性（temp）蒸發。同輪 REMOVE 了
            # 同核心飲品且 text 帶換/改語意 → ADD 繼承被移除品項的未提供
            # 欄位（來源是 cart 事實資料非 LLM 腦補，不經 slot-strip）
            if (
                removed_item_snapshot is not None
                and removed_item_snapshot.get("itemtype") == "drink"
                and any(w in text for w in ("換", "改"))
            ):
                rm_core = removed_item_snapshot.get("drink") or ""
                if rm_core and (rm_core in item_name or item_name in rm_core):
                    for field in ("quantity", "size", "temp", "customization"):
                        if field not in kwargs and removed_item_snapshot.get(field):
                            kwargs[field] = removed_item_snapshot[field]
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
                        # 追問句原文：追問鏈中客人說結帳時重放用
                        "message": add_result.get("message", ""),
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

        # add_item 失敗 → 追問補發：LLM prose（已 streaming）不含後端追問，
        # 不設 followup_text 客人會聽不到「缺什麼」死等（voice_router 對
        # not streamed_anything 輪改 yield full_text，該路徑不會重複）。
        # V9 部分過濾：prose 已在問的槽不重複補問，只補 prose 沒問到的槽
        # （combo 多缺槽 prose 問一半、followup 又整串補問 → 話術破碎）。
        # 只限單一失敗品項——多品項失敗時 prose 的追問無法對應到是問哪一項
        # （兩杯都缺 temp、prose 只問第一杯 → 第二杯追問被吞成死等），一律照補
        failed = [r for r in add_results if not r.get("ok")]
        if failed:
            failed_msgs = []
            for r in failed:
                msg = r.get("message", "")
                if len(failed) == 1 and ("？" in full_text or "?" in full_text):
                    missing = r.get("missing") or []
                    # missing_prompts 只有 combo 路徑提供；單品 add_item 各分支
                    # 逐槽 early return（missing 恆單槽）→ message 即該槽追問文字
                    prompts = r.get("missing_prompts") or (
                        {missing[0]: msg} if len(missing) == 1 else {}
                    )
                    if missing and all(s in prompts for s in missing):
                        msg = " ".join(
                            prompts[s] for s in missing if not _prose_asks_slot(full_text, s)
                        )
                if msg:
                    failed_msgs.append(msg)
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

    # ── pending 結帳接續：上輪結帳被補槽追問擋下，本輪槽位補齊 → 接回結帳 ──
    # 對 attempt 品項的 ADD（含 LLM 重發全參數）是補槽；出現其他新品項
    # = 客人改口加點，放掉結帳意圖回一般流程。zip 截斷剛好排除補槽 retry
    # 的 append（retry 只進 add_results，不進 add_kwargs_list）。
    # 補槽同句否定結帳（「先不要結帳 熱的好了」）→ 放掉 flag，不搶跑
    if (
        pending_checkout
        and not checkout_entered
        and not session.get("last_failed_attempt")
        and not any(w in text for w in _CHECKOUT_NEGATE_WORDS)
    ):
        added_other_item = any(
            r.get("ok") and ak.get("name") != pending_item_name
            for r, ak in zip(add_results, add_kwargs_list)
        )
        if session.get("cart") and not added_other_item:
            session["checkout_status"] = CK_DINE
            checkout_entered = True
            checkout_fallback = True
            logger.info("[CHECKOUT pending] 補槽完成，接回上輪結帳意圖")

    # ── 複合單句結帳推進：同句已帶內用外帶（/付款）→ 直接推進狀態機 ──
    # 放在 [ADD:...] 執行之後，確保同句加點的品項已入 cart 才 finalize。
    finalize_result = None
    if session.get("last_failed_attempt") and (checkout_entered or pending_checkout):
        # 結帳意圖遇補槽未齊（三入口共用收斂點：tag / 兜底 / flag 延續）：
        # 記/延續 pending flag，補齊那輪接回結帳
        session["pending_checkout"] = True
        if checkout_entered:
            # 撤回結帳狀態讓缺欄位追問先走，否則下輪補槽回答（如「紫米」）
            # 會被結帳狀態機吃掉造成死路
            session.pop("checkout_status", None)
            session.pop("checkout_dine_type", None)
            if not followup_text:
                # 本輪 ADD 失敗時追問已在 failed followup；attempt 來自
                # 上輪（本輪無 ADD）→ 補重放追問，客人才知道還缺什麼
                full_text = _pending_checkout_reply(session["last_failed_attempt"])
                followup_text = full_text
                patch_last_assistant(session["llm_history"], full_text)
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
