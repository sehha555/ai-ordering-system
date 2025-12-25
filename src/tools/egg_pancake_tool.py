import re
from typing import Dict, Any, List, Tuple, Optional


class EggPancakeTool:
    # menu_all.json 的蛋餅價格 [file:110]
    BASE_PRICES: Dict[str, int] = {
        "原味蛋餅": 30,
        "起司蛋餅": 40,
        "洋蔥蛋餅": 40,
        "火腿蛋餅": 40,
        "玉米蛋餅": 40,
        "肉鬆蛋餅": 40,
        "紫米蛋餅": 40,
        "高麗菜蛋餅": 45,
        "韓式泡菜蛋餅": 45,
        "培根蛋餅": 45,
        "油條蛋餅": 45,
        "薯餅蛋餅": 45,
        "鮪魚蛋餅": 55,
        "甜芋起司蛋餅": 55,
        "甜芋肉鬆蛋餅": 55,
        "醬燒肉片蛋餅": 60,
        "沙茶豬肉蛋餅": 60,
        "黑椒肉片蛋餅": 60,
    }

    # 口味同義（依你定義）
    # - 我要一個蛋餅 = 原味蛋餅
    # - 我要一個醬燒蛋餅 = 肉片蛋餅 = 醬燒肉片蛋餅
    # - 蔬菜蛋餅 = 高麗菜蛋餅
    FLAVOR_ALIASES: Dict[str, str] = {
        # 先放長的，避免被「蛋餅」吃掉
        "甜芋起司蛋餅": "甜芋起司蛋餅",
        "甜芋肉鬆蛋餅": "甜芋肉鬆蛋餅",
        "黑椒肉片蛋餅": "黑椒肉片蛋餅",
        "沙茶豬肉蛋餅": "沙茶豬肉蛋餅",
        "醬燒肉片蛋餅": "醬燒肉片蛋餅",
        "韓式泡菜蛋餅": "韓式泡菜蛋餅",
        "高麗菜蛋餅": "高麗菜蛋餅",
        "鮪魚蛋餅": "鮪魚蛋餅",
        "薯餅蛋餅": "薯餅蛋餅",
        "培根蛋餅": "培根蛋餅",
        "油條蛋餅": "油條蛋餅",
        "洋蔥蛋餅": "洋蔥蛋餅",
        "火腿蛋餅": "火腿蛋餅",
        "玉米蛋餅": "玉米蛋餅",
        "肉鬆蛋餅": "肉鬆蛋餅",
        "紫米蛋餅": "紫米蛋餅",
        "起司蛋餅": "起司蛋餅",
        "原味蛋餅": "原味蛋餅",

        # 業務同義
        "蔬菜蛋餅": "高麗菜蛋餅",
        "醬燒蛋餅": "醬燒肉片蛋餅",
        "肉片蛋餅": "醬燒肉片蛋餅",
        "醬燒肉片": "醬燒肉片蛋餅",

        # 模糊
        "蛋餅": "原味蛋餅",
    }

    # 你提供的加料單價（可重複加，例如「加兩片起司」= 2 * 10）
    ADDON_PRICES: Dict[str, int] = {
        "起司": 10,
        "高麗菜": 15,
        "火腿": 15,
        "培根": 15,
        "薯餅": 20,
        "肉片": 35,
    }

    # 加料文字同義（只用於解析「加XXX」）
    ADDON_ALIASES: Dict[str, str] = {
        "起司": "起司",
        "高麗菜": "高麗菜",
        "火腿": "火腿",
        "培根": "培根",
        "薯餅": "薯餅",
        "肉片": "肉片",
        "醬燒肉片": "肉片",
    }

    # 「同一組需求，枚舉所有可能載體，取最便宜」
    # 這些成分如果存在對應口味，會被拿來當候選載體（例如：肉片 -> 醬燒肉片蛋餅）
    CARRIER_MAP: Dict[str, str] = {
        "肉片": "醬燒肉片蛋餅",
        "薯餅": "薯餅蛋餅",
        "培根": "培根蛋餅",
        "火腿": "火腿蛋餅",
        "高麗菜": "高麗菜蛋餅",
        "起司": "起司蛋餅",
    }

    # 口味內建成分（用於：換載體時，把原本口味的成分保留下來；以及做「最便宜載體」的成本比較）
    # 沒在 ADDON_PRICES 的成分，代表不能用「加料」補，只能靠載體本身滿足
    FLAVOR_IMPLIED_COUNTS: Dict[str, Dict[str, int]] = {
        "原味蛋餅": {},
        "起司蛋餅": {"起司": 1},
        "洋蔥蛋餅": {"洋蔥": 1},
        "火腿蛋餅": {"火腿": 1},
        "玉米蛋餅": {"玉米": 1},
        "肉鬆蛋餅": {"肉鬆": 1},
        "紫米蛋餅": {"紫米": 1},
        "高麗菜蛋餅": {"高麗菜": 1},
        "韓式泡菜蛋餅": {"泡菜": 1},
        "培根蛋餅": {"培根": 1},
        "油條蛋餅": {"油條": 1},
        "薯餅蛋餅": {"薯餅": 1},
        "鮪魚蛋餅": {"鮪魚": 1},
        "甜芋起司蛋餅": {"甜芋": 1, "起司": 1},
        "甜芋肉鬆蛋餅": {"甜芋": 1, "肉鬆": 1},
        "醬燒肉片蛋餅": {"肉片": 1},
        "沙茶豬肉蛋餅": {"豬肉": 1},
        "黑椒肉片蛋餅": {"肉片": 1},
    }

    SAUCE_DEFAULT = "醬油"

    def parse_egg_pancake_utterance(self, text: str) -> Dict[str, Any]:
        qty = self._parse_quantity(text)
        base_flavor = self._detect_base_flavor(text)

        base_required = self._implied_counts(base_flavor)  # base 口味要求的成分（至少要有）
        addons_required, addons_extra = self._parse_addons_required_vs_extra(
            text=text,
            base_required=base_required
        )

        # required_counts = base_required + addons_required
        required_counts = self._add_counts(base_required, addons_required)

        # 候選載體：base_flavor +（每個 required 成分若有對應載體，也加入候選）
        carrier_candidates = self._build_carrier_candidates(base_flavor, required_counts)

        final_flavor, charge_counts = self._choose_cheapest_carrier(
            required_counts=required_counts,
            extra_counts=addons_extra,
            candidates=carrier_candidates
        )

        # 只在 2 份時主動問裝一起
        needs_pack_together_confirm = (qty == 2)
        pack_together_question = "要不要2份裝在一起？" if needs_pack_together_confirm else None

        # 預設醬油；保留辣的位置
        sauces = [self.SAUCE_DEFAULT]
        if "加辣" in text or "辣" in text:
            sauces.append("辣")
        sauces = self._dedupe_keep_order(sauces)

        # 將 charge_counts 展開成 list（含重複），方便你現有 quote 用 sum
        ingredients_add = self._expand_counts(charge_counts)

        return {
            "item_type": "egg_pancake",
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

        base_price = self.BASE_PRICES.get(flavor, 30)
        addon_total = sum(self.ADDON_PRICES.get(a, 0) for a in addons_list)
        single = base_price + addon_total
        total = single * qty

        return {
            "status": "success",
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
        zh_map = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

        m = re.search(r"(\d+)\s*個?", text)
        if m:
            return int(m.group(1))

        m2 = re.search(r"([一二兩三四五六七八九十])\s*個?", text)
        if m2:
            return zh_map.get(m2.group(1), 1)

        for k, v in [("兩個", 2), ("三個", 3), ("四個", 4), ("五個", 5)]:
            if k in text:
                return v

        return 1

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
        """
        將「加料」拆成兩類：
        - required: base_flavor 本來沒有的成分，客人說加 => 代表“想要它存在”（用於載體枚舉、且若選到已內建的載體可能變成 0 加價）
        - extra: base_flavor 已經內建的成分，客人說加 => 代表“再加一份/一片”（一定加價）
        """
        mentions = self._parse_addon_mentions_with_counts(text)

        required: Dict[str, int] = {}
        extra: Dict[str, int] = {}

        for ing, cnt in mentions.items():
            base_has = base_required.get(ing, 0)
            if base_has > 0:
                # base 口味已含該成分，這次「加」視為額外加
                extra[ing] = extra.get(ing, 0) + cnt
            else:
                # base 口味不含該成分，這次「加」視為需求成分
                required[ing] = required.get(ing, 0) + cnt

        return required, extra

    def _parse_addon_mentions_with_counts(self, text: str) -> Dict[str, int]:
        """
        支援：
        - 加起司
        - 加一片起司 / 加1片起司 / 加兩片起司
        - 加一份肉片 / 加醬燒肉片
        """
        out: Dict[str, int] = {}

        # 可辨識的加料 token（含同義）
        tokens = sorted(self.ADDON_ALIASES.keys(), key=len, reverse=True)
        token_group = "|".join(map(re.escape, tokens))

        # 數量（允許無數量，預設 1）
        # 單位（可有可無）
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
        zh_map = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        return zh_map.get(s, 1)

    def _build_carrier_candidates(self, base_flavor: str, required_counts: Dict[str, int]) -> List[str]:
        candidates = [base_flavor]

        # 任何 required 成分若有對應載體，就加入候選
        for ing in required_counts.keys():
            carrier = self.CARRIER_MAP.get(ing)
            if carrier and carrier in self.BASE_PRICES:
                candidates.append(carrier)

        # 去重保序
        return self._dedupe_keep_order(candidates)

    def _choose_cheapest_carrier(
        self,
        required_counts: Dict[str, int],
        extra_counts: Dict[str, int],
        candidates: List[str],
    ) -> Tuple[str, Dict[str, int]]:
        """
        核心規則：同一組需求，枚舉所有可能載體，取最便宜。
        成本 = 載體口味價 + (缺的 required 用加料補) + (extra 永遠加價)
        """
        best = None

        for carrier in candidates:
            base_price = self.BASE_PRICES.get(carrier)
            if base_price is None:
                continue

            implied = self._implied_counts(carrier)

            missing = self._subtract_counts(required_counts, implied)

            # 若缺的成分不能用加料補（不在 ADDON_PRICES），此候選不可行
            if any(ing not in self.ADDON_PRICES for ing in missing.keys()):
                continue

            charge = self._add_counts(missing, extra_counts)
            total = base_price + sum(self.ADDON_PRICES.get(ing, 0) * cnt for ing, cnt in charge.items())

            # tie-break：同價時，偏好「讓較貴的成分被載體內建」的載體（例如肉片優先被載體吃掉）
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

            if best is None:
                best = cand
                continue

            if cand["total"] < best["total"]:
                best = cand
                continue

            if cand["total"] == best["total"] and cand["covered_value"] > best["covered_value"]:
                best = cand
                continue

        # fallback：至少回 base
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
        # 移除 0
        out = {k: v for k, v in out.items() if v > 0}
        return out

    def _expand_counts(self, counts: Dict[str, int]) -> List[str]:
        out: List[str] = []
        for ing, cnt in counts.items():
            out.extend([ing] * cnt)
        return out

    def _dedupe_keep_order(self, items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out


egg_pancake_tool = EggPancakeTool()


if __name__ == "__main__":
    print("蛋餅工具測試（枚舉載體取最便宜）")
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
