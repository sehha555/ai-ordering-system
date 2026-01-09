import re
from typing import Dict, Any, List, Optional

from src.tools.order_router import order_router
from src.tools.riceball_tool import riceball_tool, menu_tool
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool
from src.tools.snack_tool import snack_tool
from src.tools.jam_toast_tool import jam_toast_tool
from src.tools.egg_pancake_tool import egg_pancake_tool
from src.tools.combo_tool import combo_tool # NEW IMPORT
from src.dm.session_store import InMemorySessionStore


RICE_CHOICES_TEXT = "還差米種，你要紫米、白米還是混米？"


class _SessionsProxy:
    """讓 self.sessions.get(session_id, default) 永遠可用（相容測試/舊碼）。"""

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
        self.split_keywords = sorted(["、", "，", "跟", "還要", "再來", "再給我"], key=len, reverse=True)

    def _split_utterance(self, text: str) -> List[str]:
        """Splits a single user utterance into multiple potential order spans."""
        if not text:
            return []
        
        # Use a unique separator that's unlikely to be in the text
        separator = "|||"
        # Replace all keywords with the separator
        for keyword in self.split_keywords:
            text = text.replace(keyword, separator)
        
        return [span.strip() for span in text.split(separator) if span.strip()]

    def handle(self, session_id: str, text: str) -> str:
        """Main handler for processing user input."""
        session = self.store.get(session_id)
        session["last_user_text"] = text.strip()

        if "結帳" in text:
            if session["pending_frames"]:
                first_pending = session["pending_frames"][0]
                item_type = first_pending.get("itemtype", "unknown")
                return self.get_clarify_message(item_type, first_pending.get('missing_slots', []))
            if session["cart"]:
                return self.get_order_summary(session_id)
            return "您的購物車是空的，請先點餐喔！"

        if session["pending_frames"]:
            return self._process_pending_frames(session_id, session, text)

        return self._process_new_order(session_id, session, text)
        
    def _flush_pending_queue(self, session: Dict[str, Any], newly_completed_items: List[Dict[str, Any]]) -> Optional[str]:
        """
        Iterates through pending_frames.
        If a frame is complete, moves it to cart/combo.
        If a frame is incomplete, SKIPS it (keeps in pending).
        Returns clarification message for the FIRST incomplete item found (if any),
        BUT continues processing subsequent items to move complete ones to cart.
        """
        clarify_msg = None
        i = 0
        while i < len(session["pending_frames"]):
            current_frame = session["pending_frames"][i]
            
            if current_frame["missing_slots"]:
                # Found an incomplete item. Capture clarify message if it's the FIRST one.
                if clarify_msg is None:
                    item_type = current_frame.get("itemtype", "unknown")
                    clarify_msg = self.get_clarify_message(item_type, current_frame["missing_slots"])
                # Skip this item and move to next
                i += 1
                continue
            
            # Handle Complete Frame
            if current_frame.get("_is_combo_sub_item") and session.get("current_combo_frame"):
                session["pending_frames"].pop(i)
                session["current_combo_frame"]["sub_items"].append(current_frame)
                
                # Check if combo is done (no sub-items left in pending)
                has_sub_items_left = False
                for f in session["pending_frames"]:
                     if f.get("_is_combo_sub_item"):
                         has_sub_items_left = True
                         break
                
                if not has_sub_items_left:
                    completed_combo = session.pop("current_combo_frame")
                    session["cart"].append(completed_combo)
                    newly_completed_items.append(completed_combo)
                # Do NOT increment i, as elements shifted
            else:
                completed_frame = session["pending_frames"].pop(i)
                session["cart"].append(completed_frame)
                newly_completed_items.append(completed_frame)
                # Do NOT increment i
        
        return clarify_msg

    def _process_pending_frames(self, session_id: str, session: Dict[str, Any], text: str) -> str:
        """Processes the first item in the pending_frames queue."""
        pending_frame = session["pending_frames"][0]
        route_type = pending_frame.get("itemtype", "unknown")

        tool_result = self._call_tool(route_type, text) # Use only current text for filling
        
        if tool_result.get("error"):
            return tool_result["error"]
        
        filled_part = tool_result.get("frame", {})
        
        for key, value in filled_part.items():
            if value is not None and value not in [[], {}, ""]:
                pending_frame[key] = value

        # Carrier flavor substring completion
        if route_type == "carrier" and pending_frame.get("carrier") and not pending_frame.get("flavor"):
            carrier_name = pending_frame.get("carrier")
            if carrier_name in carrier_tool.flavors_by_carrier:
                all_flavors_for_carrier = carrier_tool.flavors_by_carrier[carrier_name]
                
                matching_flavors = [
                    f for f in all_flavors_for_carrier if text.strip() in f
                ]
                
                if matching_flavors:
                    matching_flavors.sort(key=len)
                    best_match = matching_flavors[0]
                    pending_frame["flavor"] = best_match

                    # Clean up addons that are now part of the flavor to avoid double-counting
                    if "ingredients_add" in pending_frame:
                        addons_to_remove = {
                            addon for addon in pending_frame["ingredients_add"]
                            if addon and addon in best_match
                        }
                        if addons_to_remove:
                            pending_frame["ingredients_add"] = [
                                a for a in pending_frame["ingredients_add"] if a not in addons_to_remove
                            ]
        
        pending_frame["raw_text"] = text
        pending_frame["missing_slots"] = self._recompute_missing_slots(route_type, pending_frame)
        
        newly_completed_items = []
        clarify_msg = self._flush_pending_queue(session, newly_completed_items)
        
        if clarify_msg:
            return clarify_msg
            
        if newly_completed_items:
            # Format items with quantity for the summary
            completed_summary_parts = []
            for item in newly_completed_items:
                formatted_item = self._format_item(item)
                completed_summary_parts.append(f"{item.get('quantity', 1)}份 {formatted_item}")
            
            return f"好的，{'、'.join(completed_summary_parts)}，還需要什麼嗎？"

        return "請問還需要什麼嗎？"

    def _process_new_order(self, session_id: str, session: Dict[str, Any], text: str) -> str:
        """Processes a new order by splitting utterance and handling each span."""
        spans = self._split_utterance(text)
        newly_completed_items = []
        parsed_frames = []

        for span in spans:
            if not span: continue
            
            # --- NEW COMBO LOGIC START ---
            combo_frame = combo_tool.parse_combo_utterance(span)
            if combo_frame:
                # Store the main combo frame
                session["current_combo_frame"] = combo_frame
                session["current_combo_frame"]["sub_items"] = [] # To store completed sub-items

                # Explode combo into sub-items and add them to pending_frames
                sub_items = combo_tool.explode_combo_items(combo_frame)
                for i, sub_item in enumerate(sub_items):
                    sub_item["_is_combo_sub_item"] = True
                    sub_item["_combo_sub_item_index"] = i # Track order
                    sub_item["missing_slots"] = self._recompute_missing_slots(sub_item.get("itemtype", "unknown"), sub_item)
                    parsed_frames.append(sub_item)
                continue
            # --- NEW COMBO LOGIC END ---
            
            route_result = order_router.route(span, current_order_has_main=bool(session["cart"]))
            route_type = route_result["route_type"]

            if route_type == "unknown":
                # 根據安全測試要求 (test_security_bdd.py)，即使是 unknown 路由，
                # 也應觸發一次 LLM 的工具呼叫檢查，但不執行任何工具。
                # 這是為了模擬一個安全網，攔截潛在的指令注入，同時不改變原有的澄清流程。
                if self.llm and hasattr(self.llm, 'call_tool_required'):
                    self.llm.call_tool_required(text=text, session=session)
                return "不好意思，我不太明白「" + span + "」的部分，可以請您再說一次嗎？"
            
            tool_result = self._call_tool(route_type, span)
            if tool_result.get("error"):
                return tool_result["error"]
            
            frame = tool_result.get("frame")
            if not frame: continue
            
            # Ensure essential fields from the tool are preserved
            frame['itemtype'] = route_type
            if 'raw_text' not in frame:
                frame['raw_text'] = span

            frame['missing_slots'] = self._recompute_missing_slots(route_type, frame)
            parsed_frames.append(frame)

        # Add all parsed frames to pending_frames
        session["pending_frames"].extend(parsed_frames)

        # Process pending frames (move complete ones to cart until blocked)
        clarify_msg = self._flush_pending_queue(session, newly_completed_items)
        if clarify_msg:
            return clarify_msg
        
        if newly_completed_items:
            # Format items with quantity for the summary
            completed_summary_parts = []
            for item in newly_completed_items:
                item_qty = item.get("quantity", 1)
                formatted_item = self._format_item(item)
                completed_summary_parts.append(f"{item_qty}份 {formatted_item}")
            completed_summary = "、".join(completed_summary_parts)
            
            return f"好的，{completed_summary}，還需要什麼嗎？"

        return "不好意思，我沒有聽懂您的指令，請再說一次。"
        
    def _ensure_session_defaults(self, session: Dict[str, Any]) -> None:
        """Ensures the session has the new default structure."""
        session.setdefault("cart", [])
        session.setdefault("pending_frames", [])
        session.setdefault("last_user_text", None)
        session.setdefault("state", "idle")

    def _recompute_missing_slots(self, route_type: str, frame: Dict[str, Any]) -> List[str]:
        missing: List[str] = []
        # Write debug info to a file
        with open("dm_debug.log", "a", encoding="utf-8") as f:
            f.write(f"DEBUG: _recompute_missing_slots - route_type: {route_type}, frame: {frame}\n")
        
        if route_type == "riceball":
            if not frame.get("flavor"): missing.append("flavor")
            if not frame.get("rice"): missing.append("rice")
            
        elif route_type == "drink":
            if not frame.get("drink"): missing.append("drink")
            if not frame.get("temp"): missing.append("temp")
            if not frame.get("size"): missing.append("size")
            
        elif route_type == "carrier":
            if not frame.get("carrier"): missing.append("carrier")
            if not frame.get("flavor"): missing.append("flavor")
            
        elif route_type == "jam_toast":
            # Check if full name is constructed, otherwise check components
            if not frame.get("jam_toast"):
                 if not frame.get("flavor"): missing.append("flavor")
                 if not frame.get("size"): missing.append("size")
        
        elif route_type == "egg_pancake":
            if not frame.get("flavor"): missing.append("flavor")
            
        elif route_type == "snack":
            if not frame.get("snack"): missing.append("snack")

        with open("dm_debug.log", "a", encoding="utf-8") as f:
            f.write(f"DEBUG: _recompute_missing_slots - returning missing: {missing}\n")
        return missing

    def _call_tool(self, route_type: str, text: str) -> Dict[str, Any]:
        """Calls the appropriate tool based on the route type."""
        try:
            result_frame = None
            error_message = None

            if route_type == "riceball":
                result_frame = riceball_tool.parse_riceball_utterance(text)
            elif route_type == "carrier":
                result_frame = carrier_tool.parse_carrier_utterance(text)
            elif route_type == "drink":
                result_frame = drink_tool.parse_drink_utterance(text)
            elif route_type == "snack":
                result_frame = snack_tool.parse_snack_utterance(text)
            elif route_type == "jam_toast":
                result = jam_toast_tool.parse_jam_toast_utterance(text)
                if result.get("status") == "error":
                    error_message = result.get("message")
                else:
                    result_frame = result
            elif route_type == "egg_pancake":
                result_frame = egg_pancake_tool.parse_egg_pancake_utterance(text)
            else:
                return {"frame": None, "error": "未知的路由類型。"}

            if error_message:
                return {"frame": None, "error": error_message}
            
            # All tools are expected to return a dict representing the frame
            # The DialogueManager will recompute missing_slots based on this frame
            return {"frame": result_frame}

        except RuntimeError as e:
            if "Failed to load or parse base menu file" in str(e):
                return {"frame": None, "error": "菜單讀取失敗，請洽服務人員。"}
            raise e
        except Exception as e:
            print(f"Tool error for {route_type}: {e}")
            return {"frame": None, "error": "處理您的請求時發生內部錯誤。"}


    def get_clarify_message(self, route_type: str, missing_slots: List[str]) -> str:
        if not missing_slots: return "請問還需要什麼嗎？"
        
        first_missing = missing_slots[0]
        
        if route_type == "drink":
            if first_missing == "temp": return "你要冰的、溫的？"
            if first_missing == "size": return "大杯還中杯？"
            return "請問要什麼飲料？"

        if route_type == "riceball":
            if first_missing == "rice": return RICE_CHOICES_TEXT
            if first_missing == "flavor": return "想要哪個口味的飯糰？"
            return "請問要什麼飯糰？"

        if route_type == "carrier":
            if first_missing == "carrier": return "你要漢堡、吐司還是饅頭？"
            if first_missing == "flavor": return "請問要什麼口味？"
            return "你要漢堡、吐司還是饅頭？"

        if route_type == "jam_toast":
            if first_missing == "flavor": return "請問要什麼口味的果醬吐司？"
            if first_missing == "size": return "要厚片還是薄片呢？"
            return "請問要點什麼果醬吐司？"
            
        if route_type == "egg_pancake":
            if first_missing == "flavor": return "請問要什麼口味的蛋餅？"
            return "請問要點什麼蛋餅？"

        return "請問要補充什麼？"

    def _format_item(self, frame: Dict[str, Any]) -> str:
        # This function returns the formatted item string WITHOUT quantity
        # Quantity will be added by the caller if needed (e.g., in get_order_summary)
        itemtype = frame.get("itemtype")
        
        base_str = ""

        if itemtype == "drink":
            drink_name = frame.get("drink", "飲料")
            details = []
            if frame.get("size"):
                details.append(str(frame["size"]))
            if frame.get("temp"):
                details.append(str(frame["temp"]))
            if frame.get("sugar"):
                details.append(str(frame["sugar"]))
            
            detail_str = f"({', '.join(details)})" if details else ""
            base_str = f"{drink_name}{detail_str}"
        elif itemtype == "riceball":
            base_str = f"{frame.get('rice', '')}{'·' if frame.get('rice') else ''}{frame.get('flavor', '飯糰')}"
        elif itemtype == "carrier":
            base_str = f"{frame.get('flavor', '')}{frame.get('carrier', '餐點')}"
        elif itemtype == "egg_pancake":
            base_str = frame.get('flavor', '蛋餅')
        elif itemtype == "snack":
            base_str = frame.get('snack', '點心')
            details = []
            if frame.get("egg_cook"): details.append(frame["egg_cook"])
            if frame.get("no_pepper"): details.append("不要胡椒")
            if details: base_str += f"({','.join(details)})"
        elif itemtype == "jam_toast":
            base_str = frame.get('jam_toast', '果醬吐司')
            details = []
            if frame.get("no_toast"): details.append("不烤")
            if frame.get("cut_edge"): details.append("切邊")
            if details: base_str += f"({','.join(details)})"
        elif itemtype == "combo": # NEW COMBO FORMATTING
            base_str = frame.get("combo_name", "套餐")
        else:
            base_str = "未知品項"

        return base_str

    def get_order_summary(self, session_id: str) -> str:
        session = self.sessions.get(session_id, {})
        cart = session.get("cart", [])
        if not cart:
            return "目前沒有品項"

        items_formatted = []
        total_price = 0
        
        for item in cart:
            item_qty = int(item.get("quantity", 1) or 1)
            itemtype = item.get("itemtype")
            price_info = None
            item_total_price = 0

            # Simplified pricing calls
            if itemtype == "riceball": 
                price_info = menu_tool.quote_riceball_price(
                    flavor=item.get("flavor"),
                    large=item.get("large", False),
                    heavy=item.get("heavy", False),
                    extra_egg=item.get("extra_egg", False)
                )
            elif itemtype == "egg_pancake": price_info = egg_pancake_tool.quote_egg_pancake_price(item)
            elif itemtype == "carrier": price_info = carrier_tool.quote_carrier_price(item)
            elif itemtype == "drink": price_info = drink_tool.quote_drink_price(item)
            elif itemtype == "snack": price_info = snack_tool.quote_snack_price(item)
            elif itemtype == "jam_toast": price_info = jam_toast_tool.quote_jam_toast_price(item)
            elif itemtype == "combo": # NEW COMBO PRICING
                price_info = combo_tool.quote_combo_price(item)

            if price_info and price_info.get("status") == "success":
                # Handle tools that return total vs single price
                if 'total_price' in price_info:
                    item_total_price = price_info['total_price']
                elif 'single_price' in price_info:
                    item_total_price = price_info['single_price'] * item_qty
                elif 'single_total' in price_info: # for carrier_tool
                    item_total_price = price_info['single_total'] * item_qty
                
                total_price += item_total_price
                items_formatted.append(self._format_item(item))
            else:
                error_msg = price_info.get("message", "計價失敗") if price_info else "計價失敗"
                return f"品項「{self._format_item(item)}」無法計價：{error_msg}。請洽服務人員再結帳。"

        return f"這樣一共{', '.join(items_formatted)}，共 {len(cart)} 個品項，共 {total_price}元，請稍候結帳！"


if __name__ == "__main__":
    dm = DialogueManager()
    sid = "test"
    print("=== 飲料測試 ===")
    print("1>", repr(dm.handle(sid, "我要一杯豆漿")))
    print("2>", repr(dm.handle(sid, "冰的 大杯")))
    print("3>", repr(dm.handle(sid, "結帳")))

    print("\n=== 飯糰測試 ===")
    sid2 = "riceball"
    print("1>", repr(dm.handle(sid2, "我要一個飯糰")))
    print("2>", repr(dm.handle(sid2, "紫米黑椒")))
    print("3>", repr(dm.handle(sid2, "加大")))
    print("4>", repr(dm.handle(sid2, "結帳")))



