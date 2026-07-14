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

# 「N杯就好」減量句：客人要保留 N 份，LLM 慣性發 [REMOVE:品項] 整項蒸發
# 或純 prose 不發 tag（b11-03 紅茶一杯就好 → 紅茶全沒了）
_QTY_KEEP_RE = re.compile(r"([一兩二三四五六七八九十0-9]+)\s*(?:杯|個|份|顆|片)\s*就好")
# 「改成N個」改量句：LLM 機率性不發 [SET_QTY]（b9-08）
_QTY_CHANGE_RE = re.compile(r"改成?\s*([一兩二三四五六七八九十0-9]+)\s*(?:杯|個|份|顆|片)")
_ZH_NUM = {
    "一": 1,
    "兩": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _zh_qty_to_int(s: str) -> int:
    return _ZH_NUM.get(s) or (int(s) if s.isdigit() else 1)


# 客製荷包蛋拆單（b9-03/b12-09）：客製值中的獨立點心品項。
# 只認精確品名 — 裸「加蛋」是飯糰 extra_egg / 蛋餅加蛋語意，不拆
_SIDE_EGG_RE = re.compile(r"加(?:([一二兩三四五六七八九十0-9])?[顆個份粒])?\s*(荷包蛋|蔥蛋)")

# text qty 兜底（b15-07）：「兩個紫米甜飯糰」LLM 隨機漏發 qty=2 → 少做一份。
# tag 無 qty 且 text 有「N個(修飾)品項名」緊鄰 pattern（N>1）→ 補 N；
# 品項名不在 text（俗稱/context 輪）不觸發，安全方向保守
_QTY_BEFORE_ITEM_TPL = r"([一二兩三四五六七八九十0-9]+)\s*[個顆份杯片]\s*[一-鿿]{0,4}?%s"


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

# 果醬吐司封閉值域（text 佐證修正用）：「再一份花生薄片」cart 有巧克力厚片時，
# LLM 慣性把「再一份」解讀成同款+1、複製前品項 flavor/size（b10-06）。
# tag 名「果醬吐司」不在 text（text 說的是「花生薄片」）→ slot-strip 的
# context 輪豁免放行腦補值。口味與厚薄是封閉值域：text 恰好點名單一值
# 且與 tag 不符 → 以 text 為準
_JAM_FLAVORS = ("草莓", "花生", "蒜香", "奶酥", "巧克力")
_JAM_SIZES = ("厚片", "薄片")


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


def _combo_materialize_target(item_name: str, session: dict, text: str) -> Optional[str]:
    """補槽輪 LLM 把追問中套餐「具體化」成組成品項名 → 回傳應換回的套餐名。

    套餐五追問「饅頭要什麼口味」客人答「起司的」→ LLM 發 [ADD:起司蛋饅頭|...]
    （或全名後綴「起司蛋饅頭+燕麥薏仁漿」），fuzzy 解成單品饅頭入車：品項錯、
    價格錯、attempt 懸置引發空車謊言整單蒸發（b13-08）。判準：tag 品項名精確
    等於 attempt 套餐的組成品項（或整段組成串）、且 text 沒完整點名該品項 —
    text 檢查不能用 _name_in_text 的滑窗（補槽回答「起司的」的「起司」會誤中），
    客人真想點單品必說完整品名
    """
    attempt = session.get("last_failed_attempt") or {}
    combo_name = attempt.get("item_name")
    name_base = item_name.split("(")[0].strip()
    if not combo_name or item_name == combo_name or len(name_base) < 2:
        return None
    if item_name in text:
        return None
    from src.dm.tool_registry import _MENU_INDEX  # noqa: PLC0415

    full = next(
        (
            n
            for n, info in _MENU_INDEX.items()
            if info["category"] == "套餐" and n.startswith(combo_name + " ")
        ),
        None,
    )
    if not full or " " not in full:
        return None
    # 組成品項精確比對（不用字數門檻 — 2 字組成名「紅茶」「肉片」也會被
    # LLM 具體化）：全名「套餐六 鐵板麵+肉片+蛋+紅茶(大)」→ 去前綴去括號
    # 拆 + 與 *N → {鐵板麵, 肉片, 蛋, 紅茶}；也接受整段組成串（run0 型）
    suffix_base = full.split(" ", 1)[1].split("(")[0].strip()
    components = {c.split("*")[0].strip() for c in suffix_base.split("+")}
    if name_base == suffix_base or name_base in components:
        return combo_name
    return None


# 補槽值佐證的否定詞：「不要黑椒」不算 flavor=黑椒 的佐證。
# 多字詞查前 4 字窗（抓「不要加辣」這種否定詞與片段不緊鄰的形態）；
# 單字否定（不/別/免/無）僅查緊鄰前一字 — ASR 轉錄常無標點，寬窗會被
# 「不好意思」「不然」這類填充語誤觸（客人真說的口味被誤殺重問）
_NEG_PREFIXES_MULTI = ("不要", "不加", "去掉", "不用")
_NEG_PREFIXES_SINGLE = ("不", "別", "免", "無")

# 前窗掃描遇標點/空白截斷（「不用等，加辣」的「加辣」不受前句否定詞波及）
_WINDOW_BREAKS = "，。？！、 ,?!"


def _frag_contexts(frag: str, text: str):
    """yield frag 每個出現處是否為否定語境（前窗含多字否定詞或緊鄰單字否定）"""
    start = 0
    while True:
        idx = text.find(frag, start)
        if idx == -1:
            return
        window = text[max(0, idx - 4) : idx]
        for p in _WINDOW_BREAKS:
            if p in window:
                window = window.rsplit(p, 1)[-1]
        yield (
            any(neg in window for neg in _NEG_PREFIXES_MULTI) or window[-1:] in _NEG_PREFIXES_SINGLE
        )
        start = idx + 1


def _frag_affirmed(frag: str, text: str) -> bool:
    """片段是否以非否定語境出現在 user text（「蛋餅不要加辣」的「加辣」不算）"""
    return any(not negated for negated in _frag_contexts(frag, text))


def _frag_negated(frag: str, text: str) -> bool:
    """片段是否以否定語境出現在 user text（負向客製值的佐證方向）"""
    return any(_frag_contexts(frag, text))


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
    「不要加辣」前窗含否定不算）；或內容核心字有佐證，且佐證的語境方向
    必須與值的極性一致 — 肯定形式（加X）核心字須非否定出現（「不要辣」
    不佐證 加辣），否定形式（去冰/不加蔥）核心字須以否定語境出現
    （「不要冰」佐證 去冰；「加蔥」不佐證腦補的 不加蔥）"""
    if value[:2]:
        contexts = list(_frag_contexts(value[:2], text))
        if contexts:
            # 值開頭有出現 → 其語境即決定性（「蛋餅別加辣」的 加辣 全在
            # 否定語境 → 腦補，不再退到核心字判準翻案）
            return any(not negated for negated in contexts)
    core = [c for c in value if c not in _CUST_FUNC_CHARS]
    if value[:1] in _NEG_VALUE_HEADS:
        return any(_frag_negated(c, text) for c in core)
    return any(_frag_affirmed(c, text) for c in core)


# 補槽輪 text 修正候選（封閉值域槽）：value → text marker（負向語境由 _frag_affirmed 守衛）
_SLOT_CORRECTION = {
    "rice": {"紫米": "紫", "白米": "白", "混米": "混"},
    "temp": {"冰": "冰", "溫": "溫", "熱": "熱"},
    "size": {"大杯": "大", "中杯": "中"},
    "noodle": {"油麵": "油麵", "烏龍麵": "烏龍"},
}


# flavor 值域依品項而異：鐵板麵套餐 vs 果醬口味套餐（兒童餐/套餐B）
_IRON_FLAVOR_COMBOS = ("套餐六", "套餐七")
_JAM_FLAVOR_COMBOS = ("兒童餐", "套餐B")


def _slot_value_from_text(slot: str, text: str, item_name: Optional[str] = None) -> Optional[str]:
    """text 恰好肯定語境佐證該槽單一候選值 → 回該值；多值/無值/否定 → None。

    flavor 值域依品項而異，已知 item_name 時只掃對應表 —
    防跨品項誤判（套餐六 attempt 遇「花生」不可判成果醬口味）
    """
    mapping = _SLOT_CORRECTION.get(slot)
    if mapping:
        hits = [v for v, m in mapping.items() if _frag_affirmed(m, text)]
        return hits[0] if len(hits) == 1 else None
    if slot == "flavor":
        from src.dm.tool_registry import _IRON_NOODLE_FLAVOR_CANON  # noqa: PLC0415

        iron_hits = {
            canon
            for alias, canon in _IRON_NOODLE_FLAVOR_CANON.items()
            if _frag_affirmed(alias, text)
        }
        jam_hits = {f for f in _JAM_FLAVORS if _frag_affirmed(f, text)}
        if item_name:
            if item_name in _IRON_FLAVOR_COMBOS or "鐵板麵" in item_name:
                canon_hits = iron_hits
            elif item_name in _JAM_FLAVOR_COMBOS or "果醬" in item_name:
                canon_hits = jam_hits
            else:
                canon_hits = iron_hits | jam_hits
        else:
            canon_hits = iron_hits | jam_hits
        return canon_hits.pop() if len(canon_hits) == 1 else None
    return None


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
# 跨品項替換詞（swap-dedup 用）：只認明確帶替換對象的「換成/改成」。
# 「換一個/改一個」口語常是幫別人加點（「我朋友換一個綠茶」）不可觸發誤刪
_SWAP_WORDS = ("換成", "改成")


def _has_add_more_intent(text: str) -> bool:
    """user text 含加點語意（明確要新的一份，重複 ADD 去重一律讓路）"""
    return any(w in text for w in _ADD_MORE_WORDS)


def _has_modify_intent(text: str) -> bool:
    """user text 含修改語意且無加點語意（供同款重複 ADD 去重判斷）"""
    return any(w in text for w in _MODIFY_WORDS) and not _has_add_more_intent(text)


def _same_item_family(cart_item: dict, item_name: str) -> bool:
    """失敗 ADD 的裸品項名是否與 cart 既有品項同類（顯示核心名互為子字串）。
    「蛋餅」↔「培根蛋餅」、「紅茶」↔「精選紅茶」算同類；「鮪魚飯糰」↔「培根蛋餅」不算"""
    from src.dm import cart_manager  # noqa: PLC0415

    core = cart_manager.format_item(cart_item).split("(")[0].replace("·", "").replace(" ", "")
    name = item_name.replace("·", "").replace(" ", "")
    return len(name) >= 2 and (name in core or core in name)


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

    # 非結帳輪帶內用外帶詞（「起司蛋吐司加咖啡 外帶」）→ 記 hint，
    # 進結帳時不再重問（b12-02 首輪說的外帶被忘、結帳又問一次）
    if not checkout_entered:
        dine_hint = parse_dine_type(text)
        if dine_hint:
            session["dine_type_hint"] = dine_hint

    # ── [REMOVE:...] 攔截 ──
    removed_ok = False
    removed_item_snapshot: Optional[Dict[str, Any]] = None  # 同輪換品項的數量/屬性繼承用
    removed_target_name: Optional[str] = None  # 「N杯就好」減量兜底比對用
    if "[REMOVE:" in full_text:
        remove_match = REMOVE_RE.search(full_text)
        if remove_match:
            remove_target = remove_match.group(1).strip()
            removed_target_name = remove_target
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
    # 改量兜底判斷用（區塊會 strip tag）：只有「發了且成功」才算 handled —
    # LLM 會發 [SET_QTY:載體|qty=5] 這種對不到品項的 tag（b9-08），
    # 失敗輪要放行「改成N個」兜底接手
    setqty_handled = "[SET_QTY:" in full_text
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
                logger.warning("[SET_QTY] {}", sq_result.get("message"))
        full_text = SET_QTY_RE.sub("", full_text).strip()
        if not full_text:
            full_text = f"{sq_result.get('message', '已修改')}～還需要什麼？"
        patch_last_assistant(session["llm_history"], full_text)
        setqty_handled = bool(sq_result.get("ok"))

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
        # modify 語意輪誤發裸品項新 ADD 的判斷：既有 cart 快照（本輪成功 ADD
        # 不算「既有」）+ 整句 modify 語意；逐失敗品項比對是否改既有同類品項
        modify_turn = _has_modify_intent(text)
        existing_cart_snapshot = list(cart)
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
            # ── text qty 兜底：tag 漏 qty 但 text 明說數量（b15-07）──
            if "quantity" not in kwargs:
                m_qty = re.search(_QTY_BEFORE_ITEM_TPL % re.escape(item_name), text)
                if m_qty:
                    _q = _zh_qty_to_int(m_qty.group(1))
                    if _q > 1:
                        logger.info("[ADD qty-recover] text 明說 {} 份，tag 漏發補回", _q)
                        kwargs["quantity"] = _q
            # ── 補槽輪套餐組成具體化幻覺換名 ──
            # 補槽輪 LLM 不重發套餐名，把追問口味與套餐組成組合成具體品項名
            # → 換回 attempt 套餐名，參數保留接續下方補槽鏈（slot 檢查 / merge）
            materialize_combo = _combo_materialize_target(item_name, session, text)
            if materialize_combo:
                logger.info(
                    "[ADD combo-rename] 補槽輪具體化幻覺 {} → {}",
                    item_name,
                    materialize_combo,
                )
                item_name = materialize_combo
                kwargs["name"] = item_name
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
                        # 錯值先試 text 修正（封閉值域）：「黑椒 油麵」LLM 腦補
                        # noodle=烏龍麵 → 若只 strip，text 明說的油麵跟著蒸發、
                        # provided 記不到 → 補槽死循環（b9-04 套餐六）
                        corrected = _slot_value_from_text(slot, text, item_name=item_name)
                        if corrected:
                            logger.info(
                                "[ADD retry-fix] 補槽輪 {}={} 無佐證，text 修正為 {}",
                                slot,
                                kwargs[slot],
                                corrected,
                            )
                            kwargs[slot] = corrected
                        else:
                            logger.info(
                                "[ADD retry-strip] 補槽輪腦補 {}={} 無佐證，strip",
                                slot,
                                kwargs[slot],
                            )
                            kwargs.pop(slot)
                # 合法跨輪記憶 merge：前幾輪客人已提供的槽直接補回 kwargs。
                # 沒有這步，LLM 帶了舊參數會被 strip（本輪 text 無佐證）、
                # attempt.provided 覆寫時跨輪累積遺失 → 補槽永動輪（b12-08
                # 套餐五：「溫的」→「起司的」每輪只留當輪槽，永遠缺一個）
                for k, v in provided.items():
                    kwargs.setdefault(k, v)
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
            # ── 果醬吐司 text 佐證修正（封閉值域）──
            # text 恰好點名單一口味/厚薄且與 tag 不符 → 以 text 為準；
            # text 含多值（「花生厚片換巧克力」）語意模糊不動。
            # 觸發也涵蓋「花生吐司/花生厚片」型 tag 名（LLM 三種發法都見過），
            # 口味詞+吐司/厚薄詞判定 jam 品項（花生糙米漿無吐司詞不誤觸）
            is_jam_tag = "果醬吐司" in item_name or (
                any(f in item_name for f in _JAM_FLAVORS)
                and any(k in item_name for k in ("吐司", "厚片", "薄片"))
            )
            if is_jam_tag:
                text_flavors = [f for f in _JAM_FLAVORS if f in text]
                if len(text_flavors) == 1 and kwargs.get("flavor") != text_flavors[0]:
                    logger.info(
                        "[ADD jam-fix] flavor {}→{}（text 佐證）",
                        kwargs.get("flavor"),
                        text_flavors[0],
                    )
                    kwargs["flavor"] = text_flavors[0]
                text_sizes = [s for s in _JAM_SIZES if s in text]
                if len(text_sizes) == 1 and kwargs.get("size") != text_sizes[0]:
                    logger.info(
                        "[ADD jam-fix] size {}→{}（text 佐證）",
                        kwargs.get("size"),
                        text_sizes[0],
                    )
                    kwargs["size"] = text_sizes[0]
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
            if add_result.get("ok") and kwargs.get("customization"):
                # ── 客製荷包蛋拆單（b9-03/b12-09）──
                # 「懷古鹹蛋飯糰 加一顆荷包蛋」荷包蛋是獨立點心品項（$15），
                # LLM 慣性塞 customization → 沒收錢、廚房看不到。入車成功後
                # 從客製剝離、拆成獨立 ADD。只認精確點心品名（荷包蛋/蔥蛋）—
                # 「加蛋」是飯糰 extra_egg / 蛋餅加蛋語意，不碰
                cust_value = kwargs["customization"]
                m_egg = _SIDE_EGG_RE.search(cust_value)
                # 否定守衛：命中所在子句（掃回最近標點/空白）內含否定字 →
                # 不拆。固定短窗擋不住「不需要加」「不用再加」等 3 字以上
                # 否定詞；子句級寬窗誤擋方向保守（不拆＝客製原樣保留），
                # 誤拆才會反向多收 $15
                if m_egg:
                    clause_start = m_egg.start()
                    while clause_start > 0 and cust_value[clause_start - 1] not in _WINDOW_BREAKS:
                        clause_start -= 1
                    if any(
                        c in _NEG_PREFIXES_SINGLE for c in cust_value[clause_start : m_egg.start()]
                    ):
                        m_egg = None
                if m_egg:
                    egg_qty = _zh_qty_to_int(m_egg.group(1)) if m_egg.group(1) else 1
                    egg_result = _tool_registry.add_item(name=m_egg.group(2), quantity=egg_qty)
                    if not egg_result.get("ok"):
                        # 售完/解析失敗 → 不拆不剝離（客製原樣保留，行為同修復前）
                        logger.warning(
                            "[ADD egg-split] 拆單失敗（不剝離）: {} → {}",
                            m_egg.group(2),
                            egg_result.get("message"),
                        )
                    if egg_result.get("ok"):
                        add_results.append(egg_result)
                        # retried_ids 也涵蓋拆單品項：同輪副產物非客人替換/複述，
                        # 不參與 modify/swap/checkout 去重（語意同補槽 retry）
                        retried_ids.add(egg_result.get("item_id"))
                        cust = kwargs["customization"]
                        rest = (cust[: m_egg.start()] + cust[m_egg.end() :]).strip("、，, ")
                        added_item = next(
                            (
                                i
                                for i in session.get("cart", [])
                                if i.get("item_id") == add_result.get("item_id")
                            ),
                            None,
                        )
                        if added_item is not None:
                            if rest:
                                added_item["customization"] = rest
                            else:
                                added_item.pop("customization", None)
                        logger.info(
                            "[ADD egg-split] 客製拆單: {} x{}（剩餘客製: {!r}）",
                            m_egg.group(2),
                            egg_qty,
                            rest,
                        )
            if not add_result.get("ok"):
                logger.warning(
                    "[ADD tag] 執行失敗: {} → {}", add_content, add_result.get("message")
                )
                # 幻影 attempt 防護：modify 語意輪（「蛋餅不要辣」）LLM 常誤發裸
                # 品項的新 ADD（[ADD:蛋餅|customization=不要辣] 缺 flavor 失敗）。
                # 客人是改 cart 既有同類品項、非新增，記幻影 attempt 會卡死結帳
                # （pending 重放「要什麼口味」死循環）。逐品項判斷：本失敗品項與
                # 「本句被點名的既有同類 cart 品項」對得上 → 誤觸，不記 attempt、
                # 不追問（同輪其他真缺槽新品項不受影響，照常追問）
                is_modify_misfire = modify_turn and any(
                    item_mentioned_in_text(it, text) and _same_item_family(it, item_name)
                    for it in existing_cart_snapshot
                )
                if is_modify_misfire:
                    add_result["_modify_misfire"] = True
                    logger.info(
                        "[ADD modify-misfire] 改既有品項的誤發新 ADD，不記 attempt: {}", item_name
                    )
                elif add_result.get("missing"):
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
                # 只從「目標就是 attempt 品項」的 ADD 撈參數 — 跨品項裸欄位
                # 比對會把不相干新品項的屬性外洩進 attempt（「我還要一杯冰
                # 紅茶」的 temp=冰 補進套餐六 → 客人沒選過的溫度出單）
                for ak in add_kwargs_list:
                    if ak.get("name") != prev_name:
                        continue
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
                        and (
                            has_modify_words
                            or not item_mentioned_in_text(
                                new_items[0], text, ignore_rice_pieces=True
                            )
                        )
                    ):
                        cart.remove(old_items[0])
                        logger.info(
                            "[ADD modify-dedup] 修改語意移除舊品項 {} (保留本輪 {})",
                            old_items[0].get("item_id"),
                            new_items[0].get("item_id"),
                        )

                # ── 跨品項替換兜底：「換成無骨雞排蛋堡」LLM 只發 ADD 沒發 REMOVE ──
                # 新舊不同款（modify-dedup 同 key 對不上）兩個都留在車上（b12-07）。
                # 替換詞收斂到「換成/改成」（「不要辣」等客製詞不觸發誤刪）；
                # 舊品項限上一輪剛 ADD 且與新品項同 itemtype、新舊各恰 1 個
                if any(w in text for w in _SWAP_WORDS):
                    swap_new = [i for i in cart if i.get("item_id") in modify_new_ids]
                    if len(swap_new) == 1:
                        new_it = swap_new[0]
                        swap_old = [
                            i
                            for i in cart
                            if i.get("item_id") not in this_turn_ids
                            and i.get("item_id") in prev_turn_add_ids
                            and i.get("itemtype") == new_it.get("itemtype")
                            and _modify_dedup_key(i) != _modify_dedup_key(new_it)
                        ]
                        if len(swap_old) == 1:
                            cart.remove(swap_old[0])
                            logger.info(
                                "[ADD swap-dedup] 跨品項替換移除舊品項 {} (保留本輪 {})",
                                swap_old[0].get("item_id"),
                                new_it.get("item_id"),
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

            # ── 混合飲品合併：「三杯紅茶+豆漿」LLM 拆成 紅茶x3 + 豆漿x1 ──
            # 菜單有「紅茶+豆漿」「米漿+豆漿」混合品項，text 點名混合名
            # （含口語無+版「紅茶豆漿」）且本輪同時 ADD 了兩個組成單品 → 合併
            from src.dm.tool_registry import MENU_BASE_NAMES  # noqa: PLC0415

            for mixed in (n for n in MENU_BASE_NAMES if "+" in n):
                if mixed not in text and mixed.replace("+", "") not in text:
                    continue
                part_a_name, part_b_name = mixed.split("+", 1)
                new_drinks = [
                    i
                    for i in cart
                    if i.get("item_id") in this_turn_ids
                    and i.get("itemtype") == "drink"
                    and "+" not in i.get("drink", "")
                ]
                part_a = next((i for i in new_drinks if part_a_name in i.get("drink", "")), None)
                part_b = next(
                    (
                        i
                        for i in new_drinks
                        if part_b_name in i.get("drink", "") and i is not part_a
                    ),
                    None,
                )
                if part_a and part_b:
                    qty = max(
                        int(part_a.get("quantity", 1) or 1), int(part_b.get("quantity", 1) or 1)
                    )
                    size = part_a.get("size") or part_b.get("size")
                    temp = part_a.get("temp") or part_b.get("temp")
                    cart.remove(part_a)
                    cart.remove(part_b)
                    _tool_registry.add_drink(flavor=mixed, size=size, temp=temp, quantity=qty)
                    logger.info(
                        "[ADD mixed-merge] {} + {} → {} x{}",
                        part_a.get("drink"),
                        part_b.get("drink"),
                        mixed,
                        qty,
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
        # _modify_misfire 的失敗（改既有品項的誤發新 ADD）逐項排除、不追問缺槽
        failed = [r for r in add_results if not r.get("ok") and not r.get("_modify_misfire")]
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

    # ── attempt 缺槽 text 直補兜底 ──
    # 兩型：(a) 補槽輪 LLM 純 prose 不發 tag（「溫的」→「好的～」）→ 客人答的
    # 槽值蒸發、追問永動（b8-08 prose-only 補槽輪型）；(b) 本輪 ADD fail 但
    # text 還有被 strip/漏掉的缺槽值（「套餐六 冰的黑椒油麵」LLM 發錯 noodle
    # 被 strip → text 的油麵當輪撿回，不多問一輪）。
    # attempt 缺槽直接從 text 補（封閉值域，_slot_value_from_text 同一套
    # 否定守衛），全齊 retry add_item；有斬獲但未齊 → 更新 attempt 累積
    if session.get("last_failed_attempt"):
        nt_attempt = session["last_failed_attempt"]
        # 相關性閘門：加點意圖句（「我還要一杯冰紅茶」）是在點新品項不是
        # 答追問 → 不掃，防不相干句的字被撿去補槽（紅茶的冰補進套餐 temp）。
        # 純補答句（「油麵」「紅茶去冰」答套餐附飲溫度）無加點詞照掃。
        # 寧可多問一輪，不錯單
        nt_missing = list(nt_attempt.get("missing", []))
        nt_provided = dict(nt_attempt.get("provided", {}))
        nt_progressed = False
        if not _has_add_more_intent(text):
            for f in list(nt_missing):
                tv = _slot_value_from_text(f, text, item_name=nt_attempt["item_name"])
                if tv:
                    nt_provided[f] = tv
                    nt_missing.remove(f)
                    nt_progressed = True
        if nt_progressed:
            if not nt_missing:
                nt_result = _tool_registry.add_item(name=nt_attempt["item_name"], **nt_provided)
                if nt_result.get("ok"):
                    session["last_failed_attempt"] = None
                    logger.info(
                        "[ADD no-tag 補槽] text 補齊 retry 成功: {} {}",
                        nt_attempt["item_name"],
                        nt_provided,
                    )
                    if not full_text.strip():
                        full_text = f"{nt_result.get('message', '已加入')}～還需要什麼？"
                        patch_last_assistant(session["llm_history"], full_text)
                else:
                    # retry 失敗不可靜默：寫回進度（已答槽不丟）+ 補追問，
                    # 否則客人答了卻沒回饋、下輪重問 → 死路
                    session["last_failed_attempt"] = {
                        "item_name": nt_attempt["item_name"],
                        "missing": nt_result.get("missing") or nt_missing or ["flavor"],
                        "provided": {
                            k: v
                            for k, v in nt_provided.items()
                            if k not in (nt_result.get("missing") or [])
                        },
                        "message": nt_result.get("message", nt_attempt.get("message", "")),
                    }
                    followup_text = nt_result.get("message", "") or followup_text
                    if followup_text and followup_text not in full_text:
                        full_text = f"{full_text}，{followup_text}" if full_text else followup_text
                        patch_last_assistant(session["llm_history"], full_text)
                    logger.warning(
                        "[ADD no-tag 補槽] retry 失敗: {} → {}",
                        nt_provided,
                        nt_result.get("message"),
                    )
            else:
                nt_attempt["provided"] = nt_provided
                nt_attempt["missing"] = nt_missing
                logger.info("[ADD no-tag 補槽] text 補槽 {}，仍缺 {}", nt_provided, nt_missing)

    # ── 「N杯就好」減量兜底 ──
    # 「紅茶一杯就好」LLM 三種發法：[REMOVE:紅茶] 單發（整項蒸發）、
    # REMOVE+ADD 重建（正確）、純 prose 無 tag（cart 沒動）。
    # 前者回復快照改量（cart 事實資料不經 slot-strip）、後者對 text 點名的品項直接改量
    keep_m = _QTY_KEEP_RE.search(text)
    if keep_m:
        keep_qty = _zh_qty_to_int(keep_m.group(1))
        cart_now = session.get("cart", [])
        if (
            removed_ok
            and removed_item_snapshot is not None
            and removed_target_name
            and not find_cart_item_id(cart_now, removed_target_name)
        ):
            restored = dict(removed_item_snapshot)
            restored["quantity"] = keep_qty
            cart_now.append(restored)
            logger.info(
                "[REMOVE keep-qty] 「N就好」誤全移除 → 回復 {} x{}",
                removed_target_name,
                keep_qty,
            )
        elif not removed_ok and not setqty_handled:
            # 無 tag / tag 沒動到目標：text 點名且在車上的品項直接改量
            mentioned = [i for i in cart_now if item_mentioned_in_text(i, text)]
            if len(mentioned) == 1 and int(mentioned[0].get("quantity", 1) or 1) != keep_qty:
                kq_result = _tool_registry.set_item_quantity(
                    item_id=mentioned[0].get("item_id"), quantity=keep_qty
                )
                if kq_result.get("ok"):
                    logger.info(
                        "[keep-qty] 「N就好」無 tag → {} 改量 x{}",
                        mentioned[0].get("item_id"),
                        keep_qty,
                    )
                else:
                    logger.warning("[keep-qty] 改量失敗: {}", kq_result.get("message"))

    # ── 「改成N個」改量兜底 ──
    # 「改成五個好了」LLM 機率性純 prose 不發 [SET_QTY]（priming 演化後
    # 行為漂移，b9-08）→ text 點名品項、或 cart 恰一品項時直接改量
    if not setqty_handled and removed_target_name is None:
        chg_m = _QTY_CHANGE_RE.search(text)
        if chg_m and not _has_add_more_intent(text):
            chg_qty = _zh_qty_to_int(chg_m.group(1))
            cart_now = session.get("cart", [])
            mentioned = [i for i in cart_now if item_mentioned_in_text(i, text)]
            target = (
                mentioned[0]
                if len(mentioned) == 1
                else (cart_now[0] if len(cart_now) == 1 else None)
            )
            if target is not None and int(target.get("quantity", 1) or 1) != chg_qty:
                cq_result = _tool_registry.set_item_quantity(
                    item_id=target.get("item_id"), quantity=chg_qty
                )
                if cq_result.get("ok"):
                    logger.info(
                        "[qty-change] 「改成N個」無 tag → {} 改量 x{}",
                        target.get("item_id"),
                        chg_qty,
                    )

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

    # ── pending 追問棄答：重放追問後客人仍在答結帳問題（外帶/現金）──
    # 對 attempt 品項沒興趣（b11-09：不存在品項被 LLM 對映成缺槽 attempt，
    # 懸置會讓 dine/payment 回答永遠踩不進結帳 → 整單蒸發）。放掉 attempt，
    # 下方接續邏輯自然走同句推進。本輪有成功新 ADD = 改口加點，不放
    if (
        pending_checkout
        and not checkout_entered
        and session.get("last_failed_attempt")
        and (parse_dine_type(text) or parse_payment(text))
        and not any(r.get("ok") for r in add_results)
    ):
        logger.info(
            "[CHECKOUT pending] 客人答結帳問題不理追問，放掉 attempt: {}",
            session["last_failed_attempt"].get("item_name"),
        )
        session["last_failed_attempt"] = None

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
        dine_from_hint = False
        if not dine and session.get("dine_type_hint"):
            # 先前輪次說過的內用外帶（b12-02）→ 不重問，話術複述讓客人可糾正
            dine = session.pop("dine_type_hint")
            dine_from_hint = True
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
                if dine_from_hint:
                    dine_label = "內用" if dine == "dine-in" else "外帶"
                    full_text = f"好，{dine_label}～{full_text}"
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
