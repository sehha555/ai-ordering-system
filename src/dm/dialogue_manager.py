from datetime import datetime
from typing import Dict, Any, List, Optional

from src.tools.order_router import order_router
from src.tools.riceball_tool import riceball_tool
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool
from src.tools.snack_tool import snack_tool
from src.tools.jam_toast_tool import jam_toast_tool
from src.tools.egg_pancake_tool import egg_pancake_tool
from src.tools.combo_tool import combo_tool
from src.tools.menu import menu_price_service
from src.dm.session_store import InMemorySessionStore, SessionStore
from src.dm import cart_manager
from src.dm.clarify_policy import recompute_missing_slots, clarify_message


class DialogueManager:
    def __init__(self, llm: Any = None, store: Optional[SessionStore] = None, **kwargs):
        self.llm = llm
        self.store = store or InMemorySessionStore()
        self.split_keywords = sorted(
            ["、", "，", "跟", "還要", "再來", "再給我", "再一個", "再一份"], key=len, reverse=True
        )

    def get_order_summary(self, session_id):
        session = self.store.get(session_id, {})
        return cart_manager.get_order_summary(session.get("cart", []))

    def get_clarify_message(self, rtype, missing, pending_frame=None):
        return clarify_message(rtype, missing, pending_frame)

    # ─── 主狀態機 ───

    def handle(self, session_id: str, text: str) -> str:
        """Wrapper：統一處理 history 記錄與對話紀錄儲存"""
        self._last_session_id = session_id
        session = self.store.get(session_id)
        self._ensure_session_defaults(session)
        session["last_user_text"] = text.strip()

        # 記錄開始時間（新 session 首次發言）
        if session.get("started_at") is None:
            session["started_at"] = datetime.now().isoformat()

        # 記錄 user 訊息（含角色標記，供分析用）
        session["history"].append({"role": "user", "content": text.strip()})

        # 執行核心邏輯
        response = self._handle_core(session_id, session, text)

        # 記錄 assistant 回應
        session["history"].append({"role": "assistant", "content": response})

        # 結帳完成時儲存對話紀錄（避免重複儲存）
        if session.get("status") == "SUBMITTED" and not session.get("_conversation_saved"):
            from src.repository.conversation_log import conversation_log

            conversation_log.save(session_id, session)
            session["_conversation_saved"] = True

        return response

    def _handle_core(self, session_id: str, session: Dict[str, Any], text: str) -> str:
        """核心狀態機邏輯"""
        # 0. 訂單凍結檢查
        if session["status"] == "SUBMITTED":
            return "訂單已送出，若需要修改請洽店員處理喔！"

        # 1. 清空確認狀態處理
        if session.get("pending_clear_confirm"):
            affirmative = ["好", "對", "確定", "是", "ok", "是的", "要"]
            if any(text.strip() == kw for kw in affirmative) or any(
                kw in text for kw in ["可以", "沒問題"]
            ):
                session["cart"] = []
                session["pending_frames"] = []
                session.pop("current_combo_frame", None)
                session.pop("pending_clear_confirm", None)
                session["status"] = "OPEN"
                return "好的，已為您清空購物車，您可以重新開始點餐。"
            else:
                session.pop("pending_clear_confirm", None)
                return "好的，已為您保留訂單。請問還需要什麼嗎？"

        # 3. 路由判斷
        route_res = order_router.route(text, current_order_has_main=bool(session["cart"]))
        rtype = route_res["route_type"]

        # 4. 結帳/編輯功能路由
        if rtype == "checkout":
            if session["pending_frames"]:
                first = session["pending_frames"][0]
                return clarify_message(
                    first.get("itemtype", "unknown"), first.get("missing_slots", []), first
                )
            if not session["cart"]:
                return "您的購物車是空的，請先點餐喔！"
            summary = self.get_order_summary(session_id)
            return f"{summary}。請點選畫面結帳按鈕完成結帳。"

        if rtype == "clear_all":
            session["pending_clear_confirm"] = True
            return "確定要清空購物車嗎？"
        if rtype == "remove_index":
            return cart_manager.remove_by_index(session, text)
        if rtype == "cancel_last":
            return cart_manager.cancel_last(session)
        if rtype == "cancel_generic":
            return cart_manager.cancel_generic(session)

        # 5. 既有補槽流程
        if session["pending_frames"]:
            return self._process_pending_frames(session_id, session, text)

        # 6. 新訂單解析
        return self._process_new_order(session_id, session, text)

    # ─── 內部方法 ───

    def _split_utterance(self, text: str) -> List[str]:
        if not text:
            return []
        sep = "|||"
        t = text
        for kw in self.split_keywords:
            t = t.replace(kw, sep)
        return [s.strip() for s in t.split(sep) if s.strip()]

    def _flush_pending_queue(
        self, session: Dict[str, Any], newly_completed: List[Dict[str, Any]]
    ) -> Optional[str]:
        clarify_msg = None
        i = 0
        while i < len(session["pending_frames"]):
            frame = session["pending_frames"][i]
            if frame.get("missing_slots"):
                if clarify_msg is None:
                    clarify_msg = clarify_message(
                        frame.get("itemtype", "unknown"), frame["missing_slots"], frame
                    )
                i += 1
                continue
            if frame.get("_is_combo_sub_item") and session.get("current_combo_frame"):
                sub_item = session["pending_frames"].pop(i)
                session["current_combo_frame"]["sub_items"].append(sub_item)
                if not any(f.get("_is_combo_sub_item") for f in session["pending_frames"]):
                    completed = session.pop("current_combo_frame")
                    completed["itemtype"] = "combo"
                    session["cart"].append(completed)
                    newly_completed.append(completed)
            else:
                completed = session["pending_frames"].pop(i)
                session["cart"].append(completed)
                newly_completed.append(completed)
        return clarify_msg

    def _process_pending_frames(self, session_id: str, session: Dict[str, Any], text: str) -> str:
        pending = session["pending_frames"][0]
        rtype = pending.get("itemtype", "unknown")
        prefix = ""
        if pending.get("_price_driven_confirm"):
            if any(kw in text for kw in ["中杯", "是", "對", "好", "可以", "ok"]):
                pending["size"] = pending.get("_price_driven_chosen_size", "中杯")
                pending.pop("_price_driven_confirm")
                pending["missing_slots"] = recompute_missing_slots(rtype, pending)
                prefix = "好的，"
            elif "大杯" in text:
                pending["size"] = "大杯"
                pending.pop("_price_driven_confirm")
                pending["missing_slots"] = recompute_missing_slots(rtype, pending)
                prefix = "好的，"
        res = self._call_tool(rtype, text)
        if res.get("error"):
            return res["error"]
        frame = res.get("frame", {})
        for k, v in frame.items():
            if v is not None and v not in [[], {}, ""]:
                pending[k] = v
        if rtype == "carrier" and pending.get("carrier") and not pending.get("flavor"):
            matching = [
                f
                for f in carrier_tool.flavors_by_carrier.get(pending["carrier"], [])
                if text.strip() in f
            ]
            if matching:
                pending["flavor"] = sorted(matching, key=len)[0]
        pending["raw_text"] = text
        pending["missing_slots"] = recompute_missing_slots(rtype, pending)
        if (
            pending.get("_is_combo_sub_item")
            and rtype == "drink"
            and session.get("current_combo_frame")
        ):
            session["current_combo_frame"]["swap_drink"] = {
                "drink": pending.get("drink"),
                "size": pending.get("size"),
                "temp": pending.get("temp"),
            }
        newly_done = []
        msg = self._flush_pending_queue(session, newly_done)
        if msg:
            return prefix + msg
        if newly_done:
            summary = "、".join(
                [f"{i.get('quantity', 1)}份 {cart_manager.format_item(i)}" for i in newly_done]
            )
            return f"好的，{summary}，還需要什麼嗎？"
        return prefix + "請問還需要什麼嗎？"

    def _handle_drink_swap(
        self, span: str, session: Dict[str, Any], parsed_frames: List[Dict[str, Any]]
    ) -> bool:
        if not any(kw in span for kw in ["換", "改", "改成", "不要"]):
            return False
        dr = drink_tool.parse_drink_utterance(span)
        if not dr.get("drink"):
            return False
        target = next(
            (
                f
                for f in parsed_frames
                if f.get("_is_combo_sub_item") and f.get("itemtype") == "drink"
            ),
            None,
        )
        if not target:
            target = next(
                (
                    f
                    for f in session.get("pending_frames", [])
                    if f.get("_is_combo_sub_item") and f.get("itemtype") == "drink"
                ),
                None,
            )
        if not target:
            return False
        if not dr.get("size") and session.get("current_combo_frame"):
            combo_short = session["current_combo_frame"].get("combo_name")
            combo_data = combo_tool.combo_index.get(combo_short)
            if combo_data and combo_data.get("default_drink_canonical"):
                old_can = combo_data["default_drink_canonical"]
                p_old = menu_price_service.get_price("飲品", old_can)
                candidates = combo_tool.resolve_swap_drink_candidates(dr["drink"])
                chosen_can, delta, needs_confirm = combo_tool.choose_default_by_price(
                    candidates, p_old
                )
                if chosen_can and needs_confirm:
                    chosen_size = (
                        "中杯"
                        if "(中)" in chosen_can
                        else "大杯"
                        if "(大)" in chosen_can
                        else "中杯"
                    )
                    other_candidates = [c for c in candidates if c != chosen_can]

                    def fmt(name):
                        return (
                            name.replace("精選", "")
                            .replace("有糖", "")
                            .replace("無糖", "")
                            .replace("(中)", "中杯")
                            .replace("(大)", "大杯")
                        )

                    old_disp, new_disp_base = fmt(old_can), dr["drink"]
                    msg = f"原本{old_disp}{p_old}元，{new_disp_base}{chosen_size}也是{p_old}元，確認換{chosen_size}嗎？"
                    if delta > 0:
                        msg = f"原本{old_disp}{p_old}元，{new_disp_base}{chosen_size}需補差價{delta}元，確認換{chosen_size}嗎？"
                    for oc in other_candidates:
                        p_oc = menu_price_service.get_price("飲品", oc)
                        oc_size = "中杯" if "(中)" in oc else "大杯" if "(大)" in oc else "中杯"
                        oc_delta = p_oc - p_old
                        if oc_delta > 0:
                            msg += f"要{oc_size}需補差價{oc_delta}元。"
                        else:
                            msg += f"{oc_size}也是{p_oc}元。"
                    target.update(
                        {
                            "drink": dr.get("drink"),
                            "size": None,
                            "temp": dr.get("temp") or target.get("temp"),
                        }
                    )
                    target["_price_driven_confirm"] = True
                    target["_price_driven_chosen_size"] = chosen_size
                    target["_price_driven_msg"] = msg
                    target["missing_slots"] = ["_price_driven_confirm"]
                    session["current_combo_frame"]["swap_drink"] = {
                        "drink": target["drink"],
                        "size": None,
                        "temp": target["temp"],
                    }
                    return True
        target.update(
            {
                "drink": dr.get("drink"),
                "size": dr.get("size") or target.get("size"),
                "temp": dr.get("temp") or target.get("temp"),
            }
        )
        target["missing_slots"] = recompute_missing_slots("drink", target)
        session["current_combo_frame"]["swap_drink"] = {
            "drink": target["drink"],
            "size": target["size"],
            "temp": target["temp"],
        }
        return True

    def _process_new_order(self, session_id: str, session: Dict[str, Any], text: str) -> str:
        spans = self._split_utterance(text)
        newly_done, parsed = [], []
        for span in spans:
            if not span:
                continue
            combo = combo_tool.parse_combo_utterance(span)
            if combo:
                session["current_combo_frame"] = combo
                session["current_combo_frame"]["sub_items"] = []
                subs = combo_tool.explode_combo_items(combo)
                if not subs:
                    comp = session.pop("current_combo_frame")
                    session["cart"].append(comp)
                    newly_done.append(comp)
                else:
                    for s in subs:
                        s["_is_combo_sub_item"] = True
                        s["missing_slots"] = recompute_missing_slots(
                            s.get("itemtype", "unknown"), s
                        )
                        parsed.append(s)
                    self._handle_drink_swap(span, session, parsed)
                continue
            if session.get("current_combo_frame") and self._handle_drink_swap(
                span, session, parsed
            ):
                continue
            res = order_router.route(span, current_order_has_main=bool(session["cart"]))
            if res["route_type"] == "greeting":
                return "你好！歡迎光臨，請問要點什麼呢？"
            if res["route_type"] == "menu_inquiry":
                return "我們有飯糰、蛋餅、漢堡、饅頭、吐司、果醬吐司、飲料和小點心，請問想點什麼？"
            if res["route_type"] == "help":
                return "您可以直接說想點的品項，例如「一個鮪魚飯糰」或「大杯冰豆漿」，我會幫您加入購物車。"
            if res["route_type"] == "unknown":
                return res.get(
                    "clarify_question",
                    f"不好意思，我不太明白「{span}」的部分，可以請您再說一次嗎？",
                )
            tool_res = self._call_tool(res["route_type"], span)
            if tool_res.get("error"):
                return tool_res["error"]
            frame = tool_res.get("frame")
            if not frame:
                continue
            frame["itemtype"] = res["route_type"]
            frame.setdefault("raw_text", span)
            frame["missing_slots"] = recompute_missing_slots(res["route_type"], frame)
            parsed.append(frame)
        session["pending_frames"].extend(parsed)
        msg = self._flush_pending_queue(session, newly_done)
        if msg:
            return msg
        if newly_done:
            summary = "、".join(
                [f"{i.get('quantity', 1)}份 {cart_manager.format_item(i)}" for i in newly_done]
            )
            return f"好的，{summary}，還需要什麼嗎？"
        return "不好意思，我沒有聽懂您的指令，請再說一次。"

    def _call_tool(self, rtype: str, text: str) -> Dict[str, Any]:
        try:
            res = None
            if rtype == "riceball":
                res = riceball_tool.parse_riceball_utterance(text)
            elif rtype == "carrier":
                res = carrier_tool.parse_carrier_utterance(text)
            elif rtype == "drink":
                res = drink_tool.parse_drink_utterance(text)
            elif rtype == "snack":
                res = snack_tool.parse_snack_utterance(text)
            elif rtype == "jam_toast":
                tmp = jam_toast_tool.parse_jam_toast_utterance(text)
                if not tmp.get("ok"):
                    return {"frame": None, "error": tmp.get("message")}
                res = tmp
            elif rtype == "egg_pancake":
                res = egg_pancake_tool.parse_egg_pancake_utterance(text)
            return {"frame": res}
        except RuntimeError as e:
            if "Failed to load" in str(e):
                return {"frame": None, "error": "菜單讀取失敗，請洽服務人員。"}
            raise e
        except Exception:
            return {"frame": None, "error": "處理您的請求時發生內部錯誤。"}

    def _ensure_session_defaults(self, session: Dict[str, Any]) -> None:
        session.setdefault("cart", [])
        session.setdefault("pending_frames", [])
        session.setdefault("history", [])
        session.setdefault("status", "OPEN")
        session.setdefault("started_at", None)
