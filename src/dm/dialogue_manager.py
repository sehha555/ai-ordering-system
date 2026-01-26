import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.tools.order_router import order_router
from src.tools.riceball_tool import riceball_tool, menu_tool, _chinese_number_to_int
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool
from src.tools.snack_tool import snack_tool
from src.tools.jam_toast_tool import jam_toast_tool
from src.tools.egg_pancake_tool import egg_pancake_tool
from src.tools.combo_tool import combo_tool
from src.tools.menu import menu_price_service
from src.dm.session_store import InMemorySessionStore
from src.repository.order_repository import order_repo
from src.dm.session_context import SessionContext
from src.dm.llm_router import LLMRouter
from src.dm.llm_clarifier import LLMClarifier


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
    def __init__(
        self,
        llm: Any = None,
        store: Optional[InMemorySessionStore] = None,
        llm_router: Optional[LLMRouter] = None,
        llm_clarifier: Optional[LLMClarifier] = None,
        llm_enabled: bool = False,
        **kwargs
    ):
        self.llm = llm
        self.store = store or InMemorySessionStore()
        self.sessions = _SessionsProxy(self.store)
        self.llm_router = llm_router if llm_enabled else None
        self.llm_clarifier = llm_clarifier if llm_enabled else None
        self.split_keywords = sorted(["、", "，", "跟", "還要", "再來", "再給我", "再一個", "再一份"], key=len, reverse=True)

    def _split_utterance(self, text: str) -> List[str]:
        if not text: return []
        sep = "|||"
        t = text
        for kw in self.split_keywords:
            t = t.replace(kw, sep)
        return [s.strip() for s in t.split(sep) if s.strip()]

    def handle(self, session_id: str, text: str) -> str:
        # 追蹤當前會話 ID，供 get_clarify_message 使用
        self._last_session_id = session_id
        session = self.store.get(session_id)
        self._ensure_session_defaults(session)
        session["last_user_text"] = text.strip()
        session["history"].append(text.strip())

        # 0. 訂單凍結檢查
        if session["status"] == "SUBMITTED":
            return "訂單已送出，若需要修改請洽店員處理喔！"

        # 1. 結帳確認狀態處理
        if session["status"] == "CONFIRMING_CHECKOUT":
            if any(kw in text for kw in ["好", "對", "確定", "是", "ok", "要", "是的"]):
                return self._submit_order(session)
            elif any(kw in text for kw in ["取消", "不", "不要", "改一下", "還沒"]):
                session["status"] = "OPEN"
                return "好的，訂單尚未送出。請問還需要什麼嗎？"

        # 2. 清空確認狀態處理
        if session.get("pending_clear_confirm"):
            affirmative = ["好", "對", "確定", "是", "ok", "是的", "要"]
            if any(text.strip() == kw for kw in affirmative) or any(kw in text for kw in ["可以", "沒問題"]):
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
                return self.get_clarify_message(first.get("itemtype", "unknown"), first.get("missing_slots", []), first)
            if not session["cart"]:
                return "您的購物車是空的，請先點餐喔！"
            
            session["status"] = "CONFIRMING_CHECKOUT"
            summary = self.get_order_summary(session_id)
            return f"{summary}。確定要送出訂單嗎？"

        if rtype == "clear_all":
            session["pending_clear_confirm"] = True
            return "確定要清空購物車嗎？"
        if rtype == "remove_index":
            return self._handle_remove_index(session, text)
        if rtype == "cancel_last":
            return self._handle_cancel_last(session)
        if rtype == "cancel_generic":
            return self._handle_cancel_generic(session)

        # 5. 既有補槽流程
        if session["pending_frames"]:
            return self._process_pending_frames(session_id, session, text)

        # 6. 新訂單解析
        return self._process_new_order(session_id, session, text)
        
    def _submit_order(self, session: Dict[str, Any]) -> str:
        """生成 Payload 並送出訂單"""
        order_id = f"SN-{datetime.now().strftime('%m%d')}-{str(uuid.uuid4())[:4].upper()}"
        total_price = self._calculate_cart_total(session)
        
        items_payload = []
        for item in session["cart"]:
            qty = int(item.get("quantity", 1) or 1)
            pi = self._get_price_info(item)
            item_total = self._extract_total_from_pi(pi, qty)
            unit_price = item_total // qty if qty > 0 else 0
            
            items_payload.append({
                "name": self._format_item(item),
                "quantity": qty,
                "unit_price": unit_price,
                "subtotal": item_total
            })

        order_payload = {
            "order_id": order_id,
            "status": "SUCCESS",
            "created_at": datetime.now().isoformat(),
            "items": items_payload,
            "total_price": total_price,
            "raw_history": session.get("history", [])
        }
        
        session["order_payload"] = order_payload
        session["status"] = "SUBMITTED"
        
        # 落庫儲存
        order_repo.save_order(order_payload, session.get("session_id", "unknown"))
        
        return f"好的，訂單已送出！您的訂單編號是 {order_id}，請至櫃檯結帳領取。"

    def _handle_cancel_last(self, session: Dict[str, Any]) -> str:
        if session["cart"]:
            item = session["cart"].pop()
            name = self._format_item(item)
            return f"好的，已取消您最後點的：{name}。{self._get_short_summary(session)}"
        return "目前沒有品項可以取消喔。"

    def _handle_remove_index(self, session: Dict[str, Any], text: str) -> str:
        cart = session["cart"]
        if not cart: return "購物車目前是空的喔。"
        idx = self._parse_index(text)
        if idx is None: return f"抱歉，我不確定您要刪除第幾項。目前共有 {len(cart)} 項。"
        
        if 1 <= idx <= len(cart):
            removed = cart.pop(idx - 1)
            name = self._format_item(removed)
            return f"好的，已為您刪除第 {idx} 項：{name}。{self._get_short_summary(session)}"
        return f"目前只有 {len(cart)} 項品項，請確認要刪除第幾項。"

    def _handle_cancel_generic(self, session: Dict[str, Any]) -> str:
        if session["pending_frames"]:
            removed = session["pending_frames"].pop(0)
            if removed.get("_is_combo_sub_item"):
                session.pop("current_combo_frame", None)
                session["pending_frames"] = [f for f in session["pending_frames"] if not f.get("_is_combo_sub_item")]
            return "好的，已取消剛剛的變更或品項。還需要什麼嗎？"
        if session.get("pending_clear_confirm"):
            session.pop("pending_clear_confirm")
            return "好的，已取消清空操作。還需要什麼嗎？"
        return self._handle_cancel_last(session)

    def _parse_index(self, text: str) -> Optional[int]:
        patterns = [r"第\s*(\d+|[一二三四五六七八九十]+)\s*(?:項|個|份)?", r"(\d+|[一二三四五六七八九十]+)\s*(?:項|個|份)"]
        for p in patterns:
            m = re.search(p, text)
            if m:
                token = m.group(1)
                return int(token) if token.isdigit() else _chinese_number_to_int(token)
        return None

    def _get_short_summary(self, session: Dict[str, Any]) -> str:
        cart = session["cart"]
        if not cart: return "目前購物車已空。"
        total = self._calculate_cart_total(session)
        return f"目前剩餘 {len(cart)} 項品項，總計 {total}元。還需要什麼嗎？"

    def _calculate_cart_total(self, session: Dict[str, Any]) -> int:
        total = 0
        for item in session["cart"]:
            qty = int(item.get("quantity", 1) or 1)
            pi = self._get_price_info(item)
            if pi and pi.get("status") == "success":
                total += self._extract_total_from_pi(pi, qty)
        return total

    def _extract_total_from_pi(self, pi: Dict[str, Any], qty: int) -> int:
        if not pi: return 0
        if "total_price" in pi and pi["total_price"] is not None:
            return pi["total_price"]
        if "single_total" in pi:
            return pi["single_total"] * qty
        if "single_price" in pi:
            return pi["single_price"] * qty
        return 0

    def _get_price_info(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rtype = item.get("itemtype")
        pi = None
        if rtype == "riceball": pi = menu_tool.quote_riceball_price(flavor=item.get("flavor"), large=item.get("large", False), heavy=item.get("heavy", False), extra_egg=item.get("extra_egg", False))
        elif rtype == "egg_pancake": pi = egg_pancake_tool.quote_egg_pancake_price(item)
        elif rtype == "carrier": pi = carrier_tool.quote_carrier_price(item)
        elif rtype == "drink": pi = drink_tool.quote_drink_price(item)
        elif rtype == "snack": pi = snack_tool.quote_snack_price(item)
        elif rtype == "jam_toast": pi = jam_toast_tool.quote_jam_toast_price(item)
        elif rtype == "combo": pi = combo_tool.quote_combo_price(item)
        return pi

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
            if v is not None and v not in [[], {}, ""]: pending[k] = v
        if rtype == "carrier" and pending.get("carrier") and not pending.get("flavor"):
            matching = [f for f in carrier_tool.flavors_by_carrier.get(pending["carrier"], []) if text.strip() in f]
            if matching: pending["flavor"] = sorted(matching, key=len)[0]
        pending["raw_text"] = text
        pending["missing_slots"] = self._recompute_missing_slots(rtype, pending)
        if pending.get("_is_combo_sub_item") and rtype == "drink" and session.get("current_combo_frame"):
            session["current_combo_frame"]["swap_drink"] = {"drink": pending.get("drink"), "size": pending.get("size"), "temp": pending.get("temp")}
        newly_done = []
        msg = self._flush_pending_queue(session, newly_done)
        if msg: return prefix + msg
        if newly_done:
            summary = "、".join([f"{i.get('quantity', 1)}份 {self._format_item(i)}" for i in newly_done])
            return f"好的，{summary}，還需要什麼嗎？"
        return prefix + "請問還需要什麼嗎？"

    def _handle_drink_swap(self, span: str, session: Dict[str, Any], parsed_frames: List[Dict[str, Any]]) -> bool:
        if not any(kw in span for kw in ["換", "改", "改成", "不要"]): return False
        dr = drink_tool.parse_drink_utterance(span)
        if not dr.get("drink"): return False
        target = next((f for f in parsed_frames if f.get("_is_combo_sub_item") and f.get("itemtype") == "drink"), None)
        if not target: target = next((f for f in session.get("pending_frames", []) if f.get("_is_combo_sub_item") and f.get("itemtype") == "drink"), None)
        if not target: return False
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
                    def fmt(name): return name.replace("精選", "").replace("有糖", "").replace("無糖", "").replace("(中)", "中杯").replace("(大)", "大杯")
                    old_disp, new_disp_base = fmt(old_can), dr["drink"]
                    msg = f"原本{old_disp}{p_old}元，{new_disp_base}{chosen_size}也是{p_old}元，確認換{chosen_size}嗎？"
                    if delta > 0: msg = f"原本{old_disp}{p_old}元，{new_disp_base}{chosen_size}需補差價{delta}元，確認換{chosen_size}嗎？"
                    for oc in other_candidates:
                        p_oc = menu_price_service.get_price("飲品", oc)
                        oc_size = "中杯" if "(中)" in oc else "大杯" if "(大)" in oc else "中杯"
                        oc_delta = p_oc - p_old
                        if oc_delta > 0: msg += f"要{oc_size}需補差價{oc_delta}元。"
                        else: msg += f"{oc_size}也是{p_oc}元。"
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
            if session.get("current_combo_frame") and self._handle_drink_swap(span, session, parsed): continue
            res = order_router.route(span, current_order_has_main=bool(session["cart"]))
            if res["route_type"] == "unknown":
                # 如果啟用了 LLM 路由器，嘗試使用 LLM 進行分類
                if self.llm_router:
                    context = SessionContext.from_session(session)
                    llm_res = self.llm_router.classify(
                        span,
                        current_order_has_main=bool(session["cart"]),
                        session_context=context
                    )
                    # 如果 LLM 信心度足夠高，使用 LLM 的結果
                    if llm_res.get("confidence", 0) > 0.75 and llm_res.get("route_type") != "unknown":
                        res = llm_res

                # 如果仍然是未知，返回澄清提示
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
        if f == "_price_driven_confirm" and pending_frame: return pending_frame.get("_price_driven_msg", "確認換杯型嗎？")

        # 如果啟用了 LLM 澄清器，嘗試生成自然的問題
        if self.llm_clarifier:
            try:
                context = SessionContext.from_session(self.sessions.get(getattr(self, '_last_session_id', None), {}))
                question = self.llm_clarifier.generate_question(
                    rtype,
                    missing,
                    pending_frame,
                    context
                )
                return question
            except Exception:
                # 如果 LLM 失敗，備選至硬編碼問題
                pass

        # 硬編碼的備選問題（或 LLM 不可用時使用）
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
            pi = self._get_price_info(item)
            if pi and pi.get("status") == "success":
                total += self._extract_total_from_pi(pi, qty)
                items.append(self._format_item(item))
            else: return f"品項「{self._format_item(item)}」無法計價：{pi.get('message', '計價失敗') if pi else '計價失敗'}。請洽服務人員再結帳。"
        return f"這樣一共{', '.join(items)}，共 {len(cart)} 個品項，共 {total}元"

    def _ensure_session_defaults(self, session: Dict[str, Any]) -> None:
        session.setdefault("cart", [])
        session.setdefault("pending_frames", [])
        session.setdefault("history", [])
        session.setdefault("status", "OPEN")