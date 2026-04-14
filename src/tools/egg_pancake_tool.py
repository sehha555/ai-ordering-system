import re
from typing import Dict, Any, List, Tuple

from src.config.config_loader import load_json_config
from src.tools.menu import menu_price_service
from src.tools.text_utils import dedupe_keep_order, parse_quantity as _parse_quantity_util

# 從 aliases_egg_pancake.json 載入別名常數
_ep_cfg = load_json_config("aliases_egg_pancake.json")
# 從 price_rules.json 載入蛋餅加料單價（可重複加，例如「加兩片起司」= 2 * 10）
_ep_price_cfg = load_json_config("price_rules.json")


class EggPancakeTool:
    FLAVOR_ALIASES: Dict[str, str] = _ep_cfg["flavor_aliases"]

    ADDON_PRICES: Dict[str, int] = _ep_price_cfg["egg_pancake"]["addon_prices"]

    ADDON_ALIASES: Dict[str, str] = _ep_cfg["addon_aliases"]
    CARRIER_MAP: Dict[str, str] = _ep_cfg["carrier_map"]
    FLAVOR_IMPLIED_COUNTS: Dict[str, Dict[str, int]] = _ep_cfg["flavor_implied_counts"]
    SAUCE_DEFAULT: str = _ep_cfg["sauce_default"]

    def parse_egg_pancake_utterance(self, text: str) -> Dict[str, Any]:
        qty = self._parse_quantity(text)
        base_flavor = self._detect_base_flavor(text)

        base_required = self._implied_counts(base_flavor)
        addons_required, addons_extra = self._parse_addons_required_vs_extra(
            text=text, base_required=base_required
        )

        required_counts = self._add_counts(base_required, addons_required)
        carrier_candidates = self._build_carrier_candidates(base_flavor, required_counts)

        final_flavor, charge_counts = self._choose_cheapest_carrier(
            required_counts=required_counts,
            extra_counts=addons_extra,
            candidates=carrier_candidates,
        )

        needs_pack_together_confirm = qty == 2
        pack_together_question = "要不要2份裝在一起？" if needs_pack_together_confirm else None

        sauces = [self.SAUCE_DEFAULT]
        if "加辣" in text or "辣" in text:
            sauces.append("辣")
        sauces = dedupe_keep_order(sauces)

        ingredients_add = self._expand_counts(charge_counts)

        return {
            "itemtype": "egg_pancake",  # Use 'itemtype' for consistency with DM
            "quantity": qty,
            "flavor": final_flavor,
            "ingredients_add": ingredients_add,
            "ingredients_remove": self._detect_removals(text),
            "sauces": sauces,
            "needs_pack_together_confirm": needs_pack_together_confirm,
            "pack_together_question": pack_together_question,
            "packaging_preference": None,
            "raw_text": text,
        }

    def quote_egg_pancake_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        flavor = frame["flavor"]
        qty = frame["quantity"]
        addons_list: List[str] = frame.get("ingredients_add", [])
        # flavor 可能是 "原味" 或 "原味蛋餅"，get_price 需要完整名
        price_key = flavor if flavor.endswith("蛋餅") else f"{flavor}蛋餅"

        try:
            base_price = menu_price_service.get_price("蛋餅", price_key)
        except KeyError:
            return {"ok": False, "total_price": None, "message": f"找不到品項：{flavor}"}

        addon_total = sum(self.ADDON_PRICES.get(a, 0) for a in addons_list)
        single = base_price + addon_total
        total = single * qty

        return {
            "ok": True,
            "quantity": qty,
            "flavor": flavor,
            "addons": addons_list,
            "single_price": single,
            "total_price": total,
            "needs_pack_together_confirm": frame.get("needs_pack_together_confirm", False),
            "pack_together_question": frame.get("pack_together_question"),
            "message": f"{qty}個{flavor}{'+' + '+'.join(addons_list) if addons_list else ''}，共 {total}元",
        }

    def _detect_base_flavor(self, text: str) -> str:
        keys = sorted(self.FLAVOR_ALIASES.keys(), key=len, reverse=True)
        for k in keys:
            if k in text:
                return self.FLAVOR_ALIASES[k]
        return "原味蛋餅"

    def _parse_quantity(self, text: str) -> int:
        return _parse_quantity_util(text, units=("個",))

    def _detect_removals(self, text: str) -> List[str]:
        if "不加蔥" in text or "去蔥" in text:
            return ["蔥"]
        return []

    def _implied_counts(self, flavor: str) -> Dict[str, int]:
        return dict(self.FLAVOR_IMPLIED_COUNTS.get(flavor, {}))

    def _parse_addons_required_vs_extra(
        self,
        text: str,
        base_required: Dict[str, int],
    ) -> Tuple[Dict[str, int], Dict[str, int]]:
        mentions = self._parse_addon_mentions_with_counts(text)
        required: Dict[str, int] = {}
        extra: Dict[str, int] = {}
        for ing, cnt in mentions.items():
            base_has = base_required.get(ing, 0)
            if base_has > 0:
                extra[ing] = extra.get(ing, 0) + cnt
            else:
                required[ing] = required.get(ing, 0) + cnt
        return required, extra

    def _parse_addon_mentions_with_counts(self, text: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        tokens = sorted(self.ADDON_ALIASES.keys(), key=len, reverse=True)
        token_group = "|".join(map(re.escape, tokens))
        pattern = rf"加\s*(?:(\d+|[一二兩三四五六七八九十]+)\s*)?(?:片|份|塊|條)?\s*({token_group})"
        for m in re.finditer(pattern, text):
            raw_qty = m.group(1)
            raw_token = m.group(2)
            canon = self.ADDON_ALIASES.get(raw_token)
            if not canon:
                continue
            qty = self._parse_cn_or_int(raw_qty) if raw_qty else 1
            out[canon] = out.get(canon, 0) + qty
        return out

    def _parse_cn_or_int(self, s: str) -> int:
        if s is None or s == "":
            return 1
        if s.isdigit():
            return int(s)
        zh_map = {
            "一": 1,
            "二": 2,
            "兩": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        return zh_map.get(s, 1)

    def _build_carrier_candidates(
        self, base_flavor: str, required_counts: Dict[str, int]
    ) -> List[str]:
        candidates = [base_flavor]
        for ing in required_counts.keys():
            carrier = self.CARRIER_MAP.get(ing)
            if carrier:
                try:
                    menu_price_service.get_price("蛋餅", carrier)
                    candidates.append(carrier)
                except KeyError:
                    continue
        return dedupe_keep_order(candidates)

    def _choose_cheapest_carrier(
        self,
        required_counts: Dict[str, int],
        extra_counts: Dict[str, int],
        candidates: List[str],
    ) -> Tuple[str, Dict[str, int]]:
        best = None
        for carrier in candidates:
            try:
                base_price = menu_price_service.get_price("蛋餅", carrier)
            except KeyError:
                continue

            implied = self._implied_counts(carrier)
            missing = self._subtract_counts(required_counts, implied)
            if any(ing not in self.ADDON_PRICES for ing in missing.keys()):
                continue

            charge = self._add_counts(missing, extra_counts)
            total = base_price + sum(
                self.ADDON_PRICES.get(ing, 0) * cnt for ing, cnt in charge.items()
            )
            covered_value = 0
            for ing, req_cnt in required_counts.items():
                implied_cnt = implied.get(ing, 0)
                use_cnt = min(req_cnt, implied_cnt)
                covered_value += self.ADDON_PRICES.get(ing, 0) * use_cnt

            cand = {
                "carrier": carrier,
                "charge": charge,
                "total": total,
                "covered_value": covered_value,
            }
            if (
                best is None
                or cand["total"] < best["total"]
                or (
                    cand["total"] == best["total"] and cand["covered_value"] > best["covered_value"]
                )
            ):
                best = cand

        if best is None:
            return candidates[0] if candidates else "原味蛋餅", dict(extra_counts)

        return best["carrier"], best["charge"]

    def _subtract_counts(self, a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for k, va in a.items():
            vb = b.get(k, 0)
            if va - vb > 0:
                out[k] = va - vb
        return out

    def _add_counts(self, a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
        out = dict(a)
        for k, vb in b.items():
            out[k] = out.get(k, 0) + vb
        out = {k: v for k, v in out.items() if v > 0}
        return out

    def _expand_counts(self, counts: Dict[str, int]) -> List[str]:
        out: List[str] = []
        for ing, cnt in counts.items():
            out.extend([ing] * cnt)
        return out


egg_pancake_tool = EggPancakeTool()

if __name__ == "__main__":
    print("蛋餅工具測試（枚舉載體取最便宜）")
    # ... (if __name__ block remains the same)
    tests = [
        "我要一個起司蛋餅",
        "我要一個起司蛋餅加一片起司",
        "高麗菜蛋餅加醬燒肉片",
        "原味蛋餅加肉片",
        "原味蛋餅加肉片加火腿",
        "兩個起司蛋餅",
        "三個蛋餅",
    ]

    for t in tests:
        frame = egg_pancake_tool.parse_egg_pancake_utterance(t)
        quote = egg_pancake_tool.quote_egg_pancake_price(frame)
        q = quote.get("pack_together_question") or ""
        print(f"「{t}」→ {quote['message']} {q}")
