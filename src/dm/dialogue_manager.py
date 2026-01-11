import re
from typing import Dict, Any, List, Optional

from src.tools.order_router import order_router
from src.tools.riceball_tool import riceball_tool, menu_tool
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool
from src.tools.snack_tool import snack_tool
from src.tools.jam_toast_tool import jam_toast_tool
from src.tools.egg_pancake_tool import egg_pancake_tool
from src.tools.combo_tool import combo_tool 
from src.tools.menu import menu_price_service
from src.dm.session_store import InMemorySessionStore


RICE_CHOICES_TEXT = "還差米種，你要紫米、白米還是混米？"


class _SessionsProxy:
    def __init__(self, store: InMemorySessionStore):
        self._store = store

    def get(self, session_id: str, default: Optional[dict] = None) -> dict:
        try:
            return self._store.get(session_id)
        except TypeError:
            return self._store.get(session_id, default)


class DialogueManager:
    def __init__(self, llm: Any = None, store: Optional[InMemorySessionStore] = None, **kwargs):
        self.llm = llm
        self.store = store or InMemorySessionStore()
        self.sessions = _SessionsProxy(self.store)
        self.split_keywords = sorted(["、", "，", "跟", "還要", "再來", "再給我", "再一個", "再一份"], key=len, reverse=True)

    def _split_utterance(self, text: str) -> List[str]:
        if not text: return []
        sep = "|||"
        t = text
        for kw in self.split_keywords:
            t = t.replace(kw, sep)
        return [s.strip() for s in t.split(sep) if s.strip()]

    def handle(self, session_id: str, text: str) -> str:
        session = self.store.get(session_id)
        session["last_user_text"] = text.strip()

        if "結帳" in text:
            if session["pending_frames"]:
                first = session["pending_frames"][0]
                return self.get_clarify_message(first.get("itemtype", "unknown"), first.get("missing_slots", []), first)
            if session["cart"]:
                return self.get_order_summary(session_id)
            return "您的購物車是空的，請先點餐喔！"

        if session["pending_frames"]:
            return self._process_pending_frames(session_id, session, text)

        return self._process_new_order(session_id, session, text)
        
    def _flush_pending_queue(self, session: Dict[str, Any], newly_completed: List[Dict[str, Any]]) -> Optional[str]:
        clarify_msg = None
        i = 0
        while i < len(session["pending_frames"]):
            frame = session["pending_frames"][i]
            if frame.get("missing_slots"):
                if clarify_msg is None:
                    clarify_msg = self.get_clarify_message(frame.get("itemtype", "unknown"), frame["missing_slots"], frame)
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
                pending["missing_slots"] = self._recompute_missing_slots(rtype, pending)
                prefix = "好的，"
            elif "大杯" in text:
                pending["size"] = "大杯"
                pending.pop("_price_driven_confirm")
                pending["missing_slots"] = self._recompute_missing_slots(rtype, pending)
                prefix = "好的，"

        res = self._call_tool(rtype, text)
        if res.get("error"): return res["error"]
        
        frame = res.get("frame", {})
        for k, v in frame.items():
            if v is not None and v not in [[], {}, ""]:
                pending[k] = v

        if rtype == "carrier" and pending.get("carrier") and not pending.get("flavor"):
            matching = [f for f in carrier_tool.flavors_by_carrier.get(pending["carrier"], []) if text.strip() in f]
            if matching: pending["flavor"] = sorted(matching, key=len)[0]
        
        pending["raw_text"] = text
        pending["missing_slots"] = self._recompute_missing_slots(rtype, pending)
        
        if pending.get("_is_combo_sub_item") and rtype == "drink" and session.get("current_combo_frame"):
            session["current_combo_frame"]["swap_drink"] = {"drink": pending.get("drink"), "size": pending.get("size"), "temp": pending.get("temp")}
        
        newly_done = []
        msg = self._flush_pending_queue(session, newly_done)
        if msg: 
            return prefix + msg
        if newly_done:
            summary = "、".join([f"{i.get('quantity', 1)}份 {self._format_item(i)}" for i in newly_done])
            return f"好的，{summary}，還需要什麼嗎？"
        return prefix + "請問還需要什麼嗎？"

    def _handle_drink_swap(self, span: str, session: Dict[str, Any], parsed_frames: List[Dict[str, Any]]) -> bool:
        if not any(kw in span for kw in ["換", "改", "改成", "不要"]):
            return False
            
        dr = drink_tool.parse_drink_utterance(span)
        if not dr.get("drink"):
            return False
            
        target = next((f for f in parsed_frames if f.get("_is_combo_sub_item") and f.get("itemtype") == "drink"), None)
        if not target:
            target = next((f for f in session.get("pending_frames", []) if f.get("_is_combo_sub_item") and f.get("itemtype") == "drink"), None)
        
        if not target:
            return False
            
        if not dr.get("size") and session.get("current_combo_frame"):
            combo_short = session["current_combo_frame"].get("combo_name")
            combo_data = combo_tool.combo_index.get(combo_short)
            if combo_data and combo_data.get("default_drink_canonical"):
                old_can = combo_data["default_drink_canonical"]
                p_old = menu_price_service.get_price("飲品", old_can)
                candidates = combo_tool.resolve_swap_drink_candidates(dr["drink"])
                chosen_can, delta, needs_confirm = combo_tool.choose_default_by_price(candidates, p_old)
                
                if chosen_can and needs_confirm:
                    chosen_size = "中杯" if "(中)" in chosen_can else "大杯" if "(大)" in chosen_can else "中杯"
                    other_candidates = [c for c in candidates if c != chosen_can]
                    
                    # Formatting names for display
                    def fmt(name):
                        return name.replace("精選", "").replace("有糖", "").replace("無糖", "").replace("(中)", "中杯").replace("(大)", "大杯")
                    
                    old_disp = fmt(old_can)
                    new_disp_base = dr["drink"]
                    
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
                    
                    target.update({"drink": dr.get("drink"), "size": None, "temp": dr.get("temp") or target.get("temp")})
                    target["_price_driven_confirm"] = True
                    target["_price_driven_chosen_size"] = chosen_size
                    target["_price_driven_msg"] = msg
                    target["missing_slots"] = ["_price_driven_confirm"]
                    session["current_combo_frame"]["swap_drink"] = {"drink": target["drink"], "size": None, "temp": target["temp"]}
                    return True

        target.update({"drink": dr.get("drink"), "size": dr.get("size") or target.get("size"), "temp": dr.get("temp") or target.get("temp")})
        target["missing_slots"] = self._recompute_missing_slots("drink", target)
        session["current_combo_frame"]["swap_drink"] = {"drink": target["drink"], "size": target["size"], "temp": target["temp"]}
        return True

    def _process_new_order(self, session_id: str, session: Dict[str, Any], text: str) -> str:
        spans = self._split_utterance(text)
        newly_done, parsed = [], []

        for span in spans:
            if not span: continue
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
                        s["missing_slots"] = self._recompute_missing_slots(s.get("itemtype", "unknown"), s)
                        parsed.append(s)
                    self._handle_drink_swap(span, session, parsed)
                continue

            if session.get("current_combo_frame") and self._handle_drink_swap(span, session, parsed):
                continue

            res = order_router.route(span, current_order_has_main=bool(session["cart"]))
            if res["route_type"] == "unknown":
                if self.llm and hasattr(self.llm, 'call_tool_required'): self.llm.call_tool_required(text=text, session=session)
                return f"不好意思，我不太明白「{span}」的部分，可以請您再說一次嗎？"
            
            tool_res = self._call_tool(res["route_type"], span)
            if tool_res.get("error"): return tool_res["error"]
            frame = tool_res.get("frame")
            if not frame: continue
            frame['itemtype'] = res["route_type"]
            frame.setdefault('raw_text', span)
            frame['missing_slots'] = self._recompute_missing_slots(res["route_type"], frame)
            parsed.append(frame)

        session["pending_frames"].extend(parsed)
        msg = self._flush_pending_queue(session, newly_done)
        if msg: return msg
        if newly_done:
            summary = "、".join([f"{i.get('quantity', 1)}份 {self._format_item(i)}" for i in newly_done])
            return f"好的，{summary}，還需要什麼嗎？"
        return "不好意思，我沒有聽懂您的指令，請再說一次。"
        
    def _recompute_missing_slots(self, rtype: str, frame: Dict[str, Any]) -> List[str]:
        if frame.get("_price_driven_confirm"): return ["_price_driven_confirm"]
        missing = []
        if rtype == "riceball":
            if not frame.get("flavor"): missing.append("flavor")
            if not frame.get("rice"): missing.append("rice")
        elif rtype == "drink":
            if not frame.get("drink"): missing.append("drink")
            if not frame.get("temp"): missing.append("temp")
            if not frame.get("size"): missing.append("size")
        elif rtype == "carrier":
            if not frame.get("carrier"): missing.append("carrier")
            if not frame.get("flavor"): missing.append("flavor")
        elif rtype == "jam_toast":
            if not frame.get("jam_toast") and not frame.get("flavor"): missing.append("flavor")
            if not frame.get("size"): missing.append("size")
        elif rtype == "egg_pancake":
            if not frame.get("flavor"): missing.append("flavor")
        elif rtype == "snack":
            if not frame.get("snack"): missing.append("snack")
        return missing

    def _call_tool(self, rtype: str, text: str) -> Dict[str, Any]:
        try:
            res = None
            if rtype == "riceball": res = riceball_tool.parse_riceball_utterance(text)
            elif rtype == "carrier": res = carrier_tool.parse_carrier_utterance(text)
            elif rtype == "drink": res = drink_tool.parse_drink_utterance(text)
            elif rtype == "snack": res = snack_tool.parse_snack_utterance(text)
            elif rtype == "jam_toast": 
                tmp = jam_toast_tool.parse_jam_toast_utterance(text)
                if tmp.get("status") == "error": return {"frame": None, "error": tmp.get("message")}
                res = tmp
            elif rtype == "egg_pancake": res = egg_pancake_tool.parse_egg_pancake_utterance(text)
            return {"frame": res}
        except RuntimeError as e:
            if "Failed to load" in str(e): return {"frame": None, "error": "菜單讀取失敗，請洽服務人員。"}
            raise e
        except Exception: return {"frame": None, "error": "處理您的請求時發生內部錯誤。"}

    def get_clarify_message(self, rtype: str, missing: List[str], pending_frame: Optional[Dict[str, Any]] = None) -> str:
        if not missing: return "請問還需要什麼嗎？"
        f = missing[0]
        if f == "_price_driven_confirm" and pending_frame:
            return pending_frame.get("_price_driven_msg", "確認換杯型嗎？")
        if rtype == "drink":
            if f == "temp": return "你要冰的、溫的？"
            if f == "size": return "大杯還中杯？"
            return "請問要什麼飲料？"
        if rtype == "riceball":
            if f == "rice": return RICE_CHOICES_TEXT
            if f == "flavor": return "想要哪個口味的飯糰？"
        if rtype == "carrier":
            if f == "carrier": return "你要漢堡、吐司還是饅頭？"
            if f == "flavor": return "請問要什麼口味？"
        if rtype == "jam_toast":
            if f == "flavor": return "請問要什麼口味的果醬吐司？"
            if f == "size": return "要厚片還是薄片呢？"
        if rtype == "egg_pancake":
            if f == "flavor": return "請問要什麼口味的蛋餅？"
        return "請問要補充什麼？"

    def _format_item(self, frame: Dict[str, Any]) -> str:
        rtype = frame.get("itemtype")
        if rtype == "drink":
            name = frame.get("drink", "飲料")
            details = [str(frame[k]) for k in ["size", "temp", "sugar"] if frame.get(k)]
            return f"{name}({', '.join(details)})" if details else name
        if rtype == "riceball": return f"{frame.get('rice', '')}{'·' if frame.get('rice') else ''}{frame.get('flavor', '飯糰')}"
        if rtype == "carrier": return f"{frame.get('flavor', '')}{frame.get('carrier', '餐點')}"
        if rtype == "egg_pancake": return frame.get('flavor', '蛋餅')
        if rtype == "snack":
            base = frame.get('snack', '點心')
            details = [v for v in [frame.get("egg_cook"), "不要胡椒" if frame.get("no_pepper") else None] if v]
            return f"{base}({','.join(details)})" if details else base
        if rtype == "jam_toast":
            base = frame.get('jam_toast', '果醬吐司')
            details = [v for v in ["不烤" if frame.get("no_toast") else None, "切邊" if frame.get("cut_edge") else None] if v]
            return f"{base}({','.join(details)})" if details else base
        if rtype == "combo": return frame.get("combo_name", "套餐")
        return "未知品項"

    def get_order_summary(self, session_id: str) -> str:
        session = self.sessions.get(session_id, {})
        cart = session.get("cart", [])
        if not cart: return "目前沒有品項"
        items, total = [], 0
        for item in cart:
            qty = int(item.get("quantity", 1) or 1)
            rtype = item.get("itemtype")
            pi = None
            if rtype == "riceball": pi = menu_tool.quote_riceball_price(flavor=item.get("flavor"), large=item.get("large", False), heavy=item.get("heavy", False), extra_egg=item.get("extra_egg", False))
            elif rtype == "egg_pancake": pi = egg_pancake_tool.quote_egg_pancake_price(item)
            elif rtype == "carrier": pi = carrier_tool.quote_carrier_price(item)
            elif rtype == "drink": pi = drink_tool.quote_drink_price(item)
            elif rtype == "snack": pi = snack_tool.quote_snack_price(item)
            elif rtype == "jam_toast": pi = jam_toast_tool.quote_jam_toast_price(item)
            elif rtype == "combo": pi = combo_tool.quote_combo_price(item)

            if pi and pi.get("status") == "success":
                t = pi.get('total_price') or (pi.get('single_price', 0) * qty) or (pi.get('single_total', 0) * qty)
                total += t
                items.append(self._format_item(item))
            else:
                return f"品項「{self._format_item(item)}」無法計價：{pi.get('message', '計價失敗') if pi else '計價失敗'}。請洽服務人員再結帳。"
        return f"這樣一共{', '.join(items)}，共 {len(cart)} 個品項，共 {total}元，請稍候結帳！"
