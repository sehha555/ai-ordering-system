# -*- coding: utf-8 -*-
"""對話狀態機 - 支援 riceball/carrier/drink 全品類"""

from typing import Dict, Any, List
from src.tools.order_router import order_router
from src.tools.riceball_tool import riceball_tool
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool


class DialogueManager:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def handle(self, session_id: str, text: str) -> str:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "order": [],
                "current_item": None,
                "missing_slots": [],
                "route_type": None,
                "state": "idle",
            }

        session = self.sessions[session_id]
        return self._process_text(session_id, session, text)

    def _process_text(self, sid: str, session: Dict[str, Any], text: str) -> str:
        # 1) 結帳攔截
        if "結帳" in text:
            if session["missing_slots"]:
                return self._get_missing_slots_reminder(session["missing_slots"])
            if session["order"]:
                return self.get_order_summary(sid)
            return "目前沒有品項，請先點餐～"

        # 2.5) 補槽優先：上一輪在補槽就沿用上一輪 route_type，不再重新路由
        if (
            session.get("missing_slots")
            and session.get("route_type")
            and session.get("current_item")
        ):
            rt = session["route_type"]
            tool_result = self._call_tool(rt, text)

            if tool_result.get("frame"):
                # merge：保留既有已填欄位，再用新結果覆蓋/補上
                session["current_item"].update(tool_result["frame"])

                # 重新計算缺少的欄位
                session["missing_slots"] = self._recompute_missing_slots(
                    rt, session["current_item"]
                )

                if not session["missing_slots"]:
                    # 補完所有欄位 → 加入訂單
                    self._add_to_order(session)
                    return f"已加入：{self._format_item(session['order'][-1])}。還需要什麼嗎？"

                # 還有缺 → 繼續追問
                return self.get_clarify_message(rt, session["missing_slots"])

        # 2) 路由
        route_result = order_router.route(text, current_order_has_main=bool(session["order"]))
        session["route_type"] = route_result["route_type"]

        if route_result["route_type"] == "unknown":
            return route_result["clarify_question"]

        # 3) Tool 解析
        tool_result = self._call_tool(route_result["route_type"], text)

        if tool_result.get("frame"):
            session["current_item"] = tool_result["frame"]
            session["missing_slots"] = tool_result.get("missing_slots", [])

            if not session["missing_slots"]:
                # 完整品項 → 加入訂單
                self._add_to_order(session)
                return f"已加入：{self._format_item(tool_result['frame'])}。還需要什麼嗎？"

            # 缺槽 → 追問
            return self.get_clarify_message(route_result["route_type"], session["missing_slots"])

        return "抱歉，沒聽懂，請再說一次？"

    def _recompute_missing_slots(self, route_type: str, frame: Dict[str, Any]) -> List[str]:
        """根據 route_type 與 frame 重新計算缺失槽位"""
        missing: List[str] = []

        if route_type == "riceball":
            if not frame.get("flavor"):
                missing.append("flavor")
            if not frame.get("rice"):
                missing.append("rice")
            if frame.get("needs_price_confirm") and not frame.get("price_confirm"):
                missing.append("price_confirm")
            return missing

        if route_type == "drink":
            if not frame.get("drink"):
                missing.append("drink")
            if not frame.get("temp"):
                missing.append("temp")
            if not frame.get("size"):
                missing.append("size")
            return missing

        if route_type == "carrier":
            if not frame.get("flavor"):
                missing.append("flavor")
            if frame.get("carrier") is None:
                # 若 tool 有 carrier 欄位就檢查；沒有就不強制
                pass
            else:
                if not frame.get("carrier"):
                    missing.append("carrier")
            return missing

        return missing

    def _call_tool(self, route_type: str, text: str) -> Dict[str, Any]:
        """統一 tool 回傳格式：{'frame': dict|None, 'missing_slots': List[str]}"""
        try:
            if route_type == "riceball":
                result = riceball_tool.parse_riceball_utterance(text)
                return {
                    "frame": {
                        "itemtype": result.get("item_type", "riceball"),
                        "flavor": result.get("flavor"),
                        "rice": result.get("rice"),
                        "large": result.get("large", False),
                        "heavy": result.get("heavy", False),
                        "extra_egg": result.get("extra_egg", False),
                        "quantity": result.get("quantity", 1),
                        "needs_price_confirm": result.get("needs_price_confirm"),
                        "price_confirm": result.get("price_confirm"),
                    },
                    "missing_slots": result.get("missing_slots", []),
                }

            if route_type == "carrier":
                result = carrier_tool.parse_carrier_utterance(text)
                # 兼容：如果 tool 已回 {'frame':..., 'missing_slots':...} 就直接用
                if isinstance(result, dict) and "frame" in result and "missing_slots" in result:
                    return result
                return {"frame": result, "missing_slots": (result or {}).get("missing_slots", [])}

            if route_type == "drink":
                result = drink_tool.parse_drink_utterance(text)
                if isinstance(result, dict) and "frame" in result and "missing_slots" in result:
                    return result
                return {"frame": result, "missing_slots": (result or {}).get("missing_slots", [])}

        except Exception as e:
            print(f"工具錯誤 {route_type}: {e}")
            return {"frame": None, "missing_slots": []}

        return {"frame": None, "missing_slots": []}

    def get_clarify_message(self, route_type: str, missing_slots: List[str]) -> str:
        """各品類專用追問語"""
        if route_type == "drink":
            if "temp" in missing_slots:
                return "你要冰的、溫的？"
            if "size" in missing_slots:
                return "大杯還中杯？"
            return "請問要什麼飲料？"

        if route_type == "riceball":
            if "rice" in missing_slots:
                return "請問要白米、紫米還是混米？"
            if "flavor" in missing_slots:
                return "想要哪個口味？比如鮪魚、黑椒里肌、源味傳統？"
            if "price_confirm" in missing_slots:
                return "這是特殊客製，需要確認價格，請告訴店員！"
            return "請問要什麼飯糰？"

        if route_type == "carrier":
            if "carrier" in missing_slots:
                return "你要漢堡、吐司還是饅頭？"
            if "flavor" in missing_slots:
                return "請問要什麼口味？"
            return "你要漢堡、吐司還是饅頭？"

        return "請問要補充什麼？"

    def _get_missing_slots_reminder(self, missing_slots: List[str]) -> str:
        if "rice" in missing_slots:
            return "你要紫米、白米還是混米？"
        if "temp" in missing_slots:
            return "還沒說要冰的還是溫的，請先決定～"
        if "size" in missing_slots:
            return "還沒說要大杯還中杯，請先決定～"
        if "price_confirm" in missing_slots:
            return "有特殊客製需要確認，請告訴店員價格！"
        return "還有一些沒選好，請先補完再結帳！"

    def _add_to_order(self, session: Dict[str, Any]) -> None:
        if session.get("current_item"):
            session["order"].append(session["current_item"].copy())
            session["current_item"] = None
            session["missing_slots"] = []

    def _format_item(self, frame: Dict[str, Any]) -> str:
        itemtype = frame.get("itemtype")

        if itemtype == "drink":
            parts: List[str] = []
            if frame.get("size"):
                parts.append(str(frame["size"]))
            if frame.get("temp"):
                parts.append(str(frame["temp"]))
            if frame.get("sugar"):
                parts.append(str(frame["sugar"]))
            parts.append(str(frame.get("drink", "飲料")))
            return " ".join(parts)

        if itemtype == "riceball":
            rice = frame.get("rice", "")
            flavor = frame.get("flavor", "未知口味")
            extras: List[str] = []
            if frame.get("large"):
                extras.append("加大")
            if frame.get("heavy"):
                extras.append("重量")
            if frame.get("extra_egg"):
                extras.append("加蛋")
            return f"{rice}{'·' if rice else ''}{flavor}{'·' + '·'.join(extras) if extras else ''}"

        if itemtype in ("carrier", "carrier_item"):
            carrier = frame.get("carrier")
            flavor = frame.get("flavor")
            if carrier and flavor:
                return f"{flavor}{carrier}"
            if flavor:
                return str(flavor)
            if carrier:
                return str(carrier)
            return "餐點"

        return "未知品項"

    def get_order_summary(self, session_id: str) -> str:
        session = self.sessions.get(session_id, {})
        order = session.get("order", [])
        if not order:
            return "目前沒有品項"

        items = [self._format_item(item) for item in order]
        total_items = sum(int(item.get("quantity", 1) or 1) for item in order)
        return f"訂單確認：{', '.join(items)}。共 {total_items} 個品項，請稍候結帳！"


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

