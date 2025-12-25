import re
from typing import Dict, Any, Optional, List

from src.tools.snack_tool import snack_tool


class OrderRouter:
    # 用來判斷「單點語境」
    SINGLE_ITEM_MARKERS = ["單點", "一份", "一盤", "來一份", "給我一份"]

    # 明確載體關鍵字（先只做你提出的吐司/漢堡/蛋餅）
    CARRIER_KEYWORDS = ["蛋餅", "吐司", "漢堡"]

    # 模糊「X蛋」的蛋白質詞（你提到的三種）
    PROTEIN_WORDS = ["肉片", "鮪魚", "雞絲"]

    def route(self, text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
        t = text.strip()

        # 1) 單點語境：優先判斷，避免把「一份肉片」轉成肉片蛋餅
        if self._is_single_item_context(t):
            frame = snack_tool.parse_snack_utterance(t)
            quote = snack_tool.quote_snack_price(frame)

            pack_question = None
            if current_order_has_main and frame.get("suggest_pack_with_main") and frame.get("packable"):
                pack_question = "這份要不要跟前面的主餐裝在一起？"

            return {
                "route_type": "snack",
                "frame": frame,
                "quote": quote,
                "needs_clarify": bool(frame.get("missing_slots")),
                "clarify_question": "要單點哪一樣？" if frame.get("missing_slots") else None,
                "pack_question": pack_question,
            }

        # 2) 明確載體：交給對應工具（這裡先不引入 toast_tool/burger_tool，先回傳 route）
        if any(k in t for k in self.CARRIER_KEYWORDS):
            if "蛋餅" in t:
                return {
                    "route_type": "egg_pancake",
                    "needs_clarify": False,
                    "clarify_question": None,
                    "note": "已判定為蛋餅語境，請呼叫 egg_pancake_tool.parse_egg_pancake_utterance。",
                }
            if "吐司" in t:
                return {
                    "route_type": "toast",
                    "needs_clarify": False,
                    "clarify_question": None,
                    "note": "已判定為吐司語境，請呼叫 toast_tool。",
                }
            if "漢堡" in t:
                return {
                    "route_type": "burger",
                    "needs_clarify": False,
                    "clarify_question": None,
                    "note": "已判定為漢堡語境，請呼叫 burger_tool。",
                }

        # 3) 模糊「X蛋」：需要澄清載體（吐司或漢堡）
        protein = self._detect_protein_egg(t)
        if protein:
            return {
                "route_type": "ambiguous_protein_egg",
                "needs_clarify": True,
                "clarify_question": f"要做成吐司還是漢堡？（{protein}蛋）",
                "extracted": {"protein": protein},
            }

        # 4) 其他：暫時回 unknown
        return {
            "route_type": "unknown",
            "needs_clarify": True,
            "clarify_question": "想點哪一類？蛋餅、吐司、漢堡或單點？",
        }

    def _is_single_item_context(self, text: str) -> bool:
        if any(m in text for m in self.SINGLE_ITEM_MARKERS):
            return True
        # 「一份 + 肉片/醬燒肉片」這種也算
        if ("一份" in text) and any(p in text for p in ["肉片", "醬燒肉片"]):
            return True
        return False

    def _detect_protein_egg(self, text: str) -> Optional[str]:
        # 例如：肉片蛋 / 鮪魚蛋 / 雞絲蛋
        for p in self.PROTEIN_WORDS:
            if (p in text) and ("蛋" in text) and ("蛋餅" not in text) and ("吐司" not in text) and ("漢堡" not in text):
                return p
        return None


order_router = OrderRouter()


if __name__ == "__main__":
    tests = [
        "我要單點一份肉片",
        "來一份醬燒肉片",
        "我要一個肉片蛋",
        "我要一個鮪魚蛋",
        "我要醬燒肉片蛋餅",
        "我要火腿蛋吐司",
        "我要肉片蛋漢堡",
    ]

    for t in tests:
        r = order_router.route(t, current_order_has_main=True)
        print(f"「{t}」→ {r.get('route_type')} / clarify={r.get('clarify_question')} / pack={r.get('pack_question')}")