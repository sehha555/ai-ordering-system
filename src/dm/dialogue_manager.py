from __future__ import annotations

import re
from typing import Dict, Any, Optional, List, Tuple

from src.dm.session_store import InMemorySessionStore
from src.dm.clarify_policy import question_for_missing_slot
from src.dm.slot_parsers import parse_strict_price_confirm
from src.services.llm_tool_caller import LLMToolCaller
from src.tools.order_router import order_router
from src.tools.riceball_tool import menu_tool


# ---- Safety / limits ----
MAX_INPUT_LEN = 240
MAX_SEGMENTS = 6


def _is_checkout_utterance(text: str) -> bool:
    t = (text or "").strip()
    markers = ["結帳", "買單", "這樣就好", "就這樣", "不需要", "不用", "不用了", "沒了", "就這些", "好了"]
    return any(m in t for m in markers)


def _normalize_text(text: str) -> str:
    t = (text or "").strip()
    if len(t) > MAX_INPUT_LEN:
        t = t[:MAX_INPUT_LEN]
    return t


_SPLIT_RE = re.compile(
    r"""
    (?:[，,、；;。\.]+)|
    (?:\s*(?:跟|和|以及|再|還要|還想要|另外|加上)\s*)
    """,
    re.VERBOSE,
)


def _split_multi_items(text: str, max_segments: int = MAX_SEGMENTS) -> List[str]:
    """
    把單句拆成多段品項描述，過濾掉純結帳片段。
    """
    t = _normalize_text(text)
    parts = [p.strip() for p in _SPLIT_RE.split(t) if p and p.strip()]
    parts = [p for p in parts if not _is_checkout_utterance(p)]
    return parts[:max_segments]


def _format_specs(frame: Dict[str, Any]) -> str:
    parts: List[str] = []
    if frame.get("large"):
        parts.append("加大")
    if frame.get("heavy"):
        parts.append("重量版")
    if frame.get("extra_egg"):
        parts.append("加蛋")
    if frame.get("ingredients_add"):
        parts.append("+" + ",".join(frame["ingredients_add"]))
    return "·".join(parts)


def _next_missing(frame: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not frame.get("flavor"):
        missing.append("flavor")
    if not frame.get("rice"):
        missing.append("rice")
    if frame.get("needs_price_confirm"):
        missing.append("price_confirm")
    return missing


class DialogueManager:
    """
    支援：
    - 多輪單項：沿用 pending.slot 補齊
    - 單輪多項：split -> queue -> 逐段處理，遇到缺槽就暫停追問；補完後自動續跑 queue
    """

    def __init__(self, store: Optional[InMemorySessionStore] = None, llm: Optional[LLMToolCaller] = None):
        self.store = store or InMemorySessionStore()
        self.llm = llm or LLMToolCaller()

        self.tool_map = {
            "parse_riceball_utterance": menu_tool.parse_riceball_utterance,
            "quote_riceball_price": menu_tool.quote_riceball_price,
            "quote_riceball_customization_price": menu_tool.quote_riceball_customization_price,
        }

        self.allowed_args = {
            "parse_riceball_utterance": {"text"},
            "quote_riceball_price": {"flavor", "large", "heavy", "extra_egg"},
            "quote_riceball_customization_price": {
                "flavor",
                "add_ingredients",
                "remove_ingredients",
                "only_ingredients",
                "only_mode",
            },
        }

    def handle(self, session_id: str, text: str) -> str:
        text = _normalize_text(text)

        state = self.store.get(session_id) or {}
        pending = state.get("pending") or {}
        pending.setdefault("slot", None)
        pending.setdefault("frame", None)
        pending.setdefault("queue", [])
        if not isinstance(pending["queue"], list):
            pending["queue"] = []
        state["pending"] = pending

        cart = state.setdefault("cart", [])

        added_desc: List[str] = []
        checkout_intent = _is_checkout_utterance(text)

        # 單輪多項：只在「非補槽狀態」時才拆句入 queue
        if pending["slot"] not in ("rice", "flavor", "price_confirm"):
            segs = _split_multi_items(text)
            if segs:
                # 第一段當作本輪主處理，其餘塞 queue
                head, rest = segs[0], segs[1:]
                if rest:
                    pending["queue"].extend(rest)
                text = head

        # 主 loop：本輪輸入 + queue 自動續跑
        while True:
            slot = pending.get("slot")

            # 0) await_more_items + 結帳
            if slot == "await_more_items" and checkout_intent and not pending["queue"]:
                if not cart:
                    return "目前還沒有餐點要結帳。你想點什麼？"
                return self._final_checkout_message(session_id, cart)

            # A) 補 slot：rice / flavor
            if slot in ("rice", "flavor"):
                frame = pending.get("frame") or {}
                parsed = menu_tool.parse_riceball_utterance(text)

                if slot == "rice":
                    if not parsed.get("rice"):
                        return self._prefix_added(added_desc, "請問要白米、紫米還是混米？")
                    frame["rice"] = parsed["rice"]
                else:  # flavor
                    if not parsed.get("flavor"):
                        return self._prefix_added(added_desc, "請再說一次口味（例如：源味傳統、黑椒里肌、韓式泡菜…）")
                    frame["flavor"] = parsed["flavor"]

                missing = _next_missing(frame)
                if missing:
                    next_slot = "price_confirm" if "price_confirm" in missing else missing[0]
                    pending["slot"] = next_slot
                    pending["frame"] = frame
                    self.store.set(session_id, state)
                    return self._prefix_added(added_desc, question_for_missing_slot(frame, missing))

                # frame 完整 -> 入 cart
                cart.append(frame)
                added_desc.append(self._format_item_desc(frame))

                pending["slot"] = "await_more_items"
                pending["frame"] = None

                # 自動續跑 queue（同一輪輸入）
                nxt = self._pop_next_segment(pending)
                if nxt is None:
                    self.store.set(session_id, state)
                    return self._added_and_ask_more(added_desc)

                text = nxt
                checkout_intent = _is_checkout_utterance(text)
                continue

            # A2) 補 slot：price_confirm
            if slot == "price_confirm":
                r = parse_strict_price_confirm(text, min_price=35, step=5)
                if not r["ok"]:
                    return self._prefix_added(added_desc, r["message"])

                frame = pending.get("frame") or {}
                frame["price_confirm"] = r["price"]

                cart.append(frame)
                added_desc.append(self._format_item_desc(frame))

                pending["slot"] = "await_more_items"
                pending["frame"] = None

                nxt = self._pop_next_segment(pending)
                if nxt is None:
                    self.store.set(session_id, state)
                    return self._added_and_ask_more(added_desc)

                text = nxt
                checkout_intent = _is_checkout_utterance(text)
                continue

            # B) Router（非飯糰路由先回澄清 / 或提示尚未支援）
            route = order_router.route(text, current_order_has_main=bool(state.get("has_main")))
            route_type = route.get("route_type")

            if route_type == "snack":
                frame = route.get("frame") or {}
                missing = frame.get("missing_slots") or []
                if missing:
                    # snack 的缺槽策略先簡化：直接問 clarify_question
                    q = route.get("clarify_question") or "要單點哪一樣？"
                    self.store.set(session_id, state)
                    return self._prefix_added(added_desc, q)

                cart.append(frame)
                added_desc.append(frame.get("name") or frame.get("item_name") or "單點")
                pending["slot"] = "await_more_items"

                nxt = self._pop_next_segment(pending)
                if nxt is None:
                    self.store.set(session_id, state)
                    return self._added_and_ask_more(added_desc)

                text = nxt
                checkout_intent = _is_checkout_utterance(text)
                continue

            if route_type in ("egg_pancake", "toast", "burger"):
                # 重要：不要把 route.note 回給使用者（資訊洩漏）
                self.store.set(session_id, state)
                return self._prefix_added(
                    added_desc,
                    "目前蛋餅/吐司/漢堡的自動解析還沒接上（正在施工中）。先用飯糰或單點測試可以嗎？",
                )

            if route_type in ("ambiguous_protein_egg", "unknown"):
                q = route.get("clarify_question") or "想點哪一類？"
                self.store.set(session_id, state)
                return self._prefix_added(added_desc, q)

            # C) LLM tool-calling：主要用來把「飯糰自然語句」轉成 frame
            call = self.llm.call_tool_required(text, menu_tool.get_openai_tools_schema())
            if not call.get("ok"):
                self.store.set(session_id, state)
                return self._prefix_added(added_desc, "請再說清楚一點～")

            exec_res = self.llm.execute_tool_call(
                call["tool_call"],
                tool_map=self.tool_map,
                allowed_args=self.allowed_args,
            )
            if not exec_res.get("ok"):
                self.store.set(session_id, state)
                return self._prefix_added(added_desc, "系統解析失敗，請再說一次～")

            frame = exec_res.get("result") or {}
            state["has_main"] = True

            missing = frame.get("missing_slots") or _next_missing(frame)
            if missing:
                next_slot = "price_confirm" if "price_confirm" in missing else missing[0]
                pending["slot"] = next_slot
                pending["frame"] = frame
                self.store.set(session_id, state)
                return self._prefix_added(added_desc, question_for_missing_slot(frame, missing))

            cart.append(frame)
            added_desc.append(self._format_item_desc(frame))
            pending["slot"] = "await_more_items"

            nxt = self._pop_next_segment(pending)
            if nxt is None:
                self.store.set(session_id, state)
                return self._added_and_ask_more(added_desc)

            text = nxt
            checkout_intent = _is_checkout_utterance(text)
            continue

    # ---- Helpers ----

    def _pop_next_segment(self, pending: Dict[str, Any]) -> Optional[str]:
        q = pending.get("queue") or []
        if not q:
            return None
        # FIFO
        seg = q.pop(0)
        seg = (seg or "").strip()
        return seg or None

    def _format_item_desc(self, frame: Dict[str, Any]) -> str:
        flavor = frame.get("flavor") or ""
        rice = frame.get("rice") or ""
        specs = _format_specs(frame)
        item_desc = f"{flavor}{rice}"
        if specs:
            item_desc += f"（{specs}）"
        qty = int(frame.get("quantity") or 1)
        if qty > 1:
            item_desc += f" x{qty}"
        return item_desc

    def _prefix_added(self, added_desc: List[str], msg: str) -> str:
        if not added_desc:
            return msg
        joined = "、".join(added_desc)
        return f"已先幫你加入：{joined}。\n{msg}"

    def _added_and_ask_more(self, added_desc: List[str]) -> str:
        if not added_desc:
            return "還需要什麼嗎？"
        joined = "、".join(added_desc)
        return f"已加入：{joined}。\n還需要什麼嗎？"

    def _final_checkout_message(self, session_id: str, cart: List[Dict[str, Any]]) -> str:
        total = 0

        for frame in cart:
            qty = int(frame.get("quantity") or 1)
            qty = qty if qty > 0 else 1

            # 人工選價：視為該品項單價
            if frame.get("price_confirm") is not None:
                total += int(frame["price_confirm"]) * qty
                continue

            # 目前結帳邏輯以飯糰為主（其他品類後續接上再擴充）
            if not frame.get("flavor"):
                # 略過不可計價的 frame，避免 KeyError
                continue

            base = menu_tool.quote_riceball_price(
                flavor=frame["flavor"],
                large=frame.get("large", False),
                heavy=frame.get("heavy", False),
                extra_egg=frame.get("extra_egg", False),
            )

            addon = menu_tool.quote_riceball_customization_price(
                flavor=frame["flavor"],
                add_ingredients=frame.get("ingredients_add", []),
                remove_ingredients=frame.get("ingredients_remove", []),
                only_ingredients=frame.get("ingredients_only", []),
                only_mode=(frame.get("ingredients_mode") == "only"),
            )

            if addon.get("status") == "needs_price_confirm":
                state = self.store.get(session_id) or {}
                pending = state.get("pending") or {}
                pending["slot"] = "price_confirm"
                pending["frame"] = frame
                pending.setdefault("queue", [])
                state["pending"] = pending
                self.store.set(session_id, state)
                return "你想要包多少錢的？（最低35元、5元級距，例如35/40/45）"

            price = int(base.get("total_price") or 0) + int(addon.get("addon_total") or 0)
            total += price * qty

        # 視為送單：清空 session
        self.store.clear(session_id)
        return f"這樣一共 {total} 元。"
