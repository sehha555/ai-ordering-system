import re
from typing import Any, Dict, List, Optional, Tuple

from src.tools.menu import menu_price_service
from src.config.alias_loader import load_combo_aliases

class ComboTool:
    def __init__(self):
        self.alias_cfg = load_combo_aliases()
        self._load_menu_data()

    def _load_menu_data(self):
        """
        Loads combo data from the menu service and builds internal lookups.
        """
        all_items = menu_price_service.get_raw_menu()
        self.combo_index = {}  
        
        self.item_name_to_category = {item['name']: item['category'] for item in all_items if 'name' in item and 'category' in item}
        self.all_item_names = sorted(list(self.item_name_to_category.keys()), key=len, reverse=True)
        self.simple_name_to_canonical = {}
        
        self.manual_aliases = self.alias_cfg.get("manual_aliases", {})
        norm_rules = self.alias_cfg.get("normalize_rules", {})
        self.remove_tokens = norm_rules.get("remove_tokens", [])
        self.regex_removals = norm_rules.get("regex_removals", [])

        for name in self.all_item_names:
            # Full simplification
            s = name
            for t in self.remove_tokens: s = s.replace(t, "")
            for p in self.regex_removals: s = re.sub(p, '', s)
            s = s.strip()
            if s: self.simple_name_to_canonical[s] = name
            
            # Keep parens
            sp = name
            for t in self.remove_tokens: sp = sp.replace(t, "")
            sp = sp.strip()
            if sp and sp != s: self.simple_name_to_canonical[sp] = name

        for alias, can in self.manual_aliases.items():
            if can in self.item_name_to_category: self.simple_name_to_canonical[alias] = can

        # Populate combo_index
        for item in all_items:
            if item.get("category") == "套餐":
                fn = item.get("name")
                if not fn: continue
                m = re.match(r"^(套餐[一二三四五六七八九十ABCDE]|兒童餐)\s*(.*)", fn)
                if m:
                    short = m.group(1)
                    self.combo_index[short] = {"price": item["price"], "desc": m.group(2).strip(), "full_name": fn, "default_drink_canonical": None}

        # Build sub_item_to_combo_names and find default drinks
        self.sub_item_to_combo_names = {} 
        for short in self.combo_index:
             subs = self.explode_combo_items({"combo_name": short})
             for sub in subs:
                 can = sub.get("raw_text")
                 if sub.get("itemtype") == "drink": self.combo_index[short]["default_drink_canonical"] = can
                 for sname, mcan in self.simple_name_to_canonical.items():
                     if mcan == can:
                         if sname not in self.sub_item_to_combo_names: self.sub_item_to_combo_names[sname] = []
                         if short not in self.sub_item_to_combo_names[sname]: self.sub_item_to_combo_names[sname].append(short)

    def parse_combo_utterance(self, text: str) -> Optional[Dict[str, Any]]:
        for short in self.combo_index:
            if short in text: return {"itemtype": "combo", "combo_name": short, "quantity": 1, "raw_text": text}

        found = [name for name in self.sub_item_to_combo_names if name in text]
        if not found: return None
        if len(found) == 1 and (found[0] in self.alias_cfg.get("allow_single_item_keywords", []) or found[0] in self.simple_name_to_canonical): return None

        res = set(self.sub_item_to_combo_names.get(found[0], []))
        for i in range(1, len(found)): res.intersection_update(self.sub_item_to_combo_names.get(found[i], []))
        if len(res) == 1: return {"itemtype": "combo", "combo_name": res.pop(), "quantity": 1, "raw_text": text}
        return None

    def find_canonical_drink_name(self, drink: str, size: str) -> Optional[str]:
        if not drink: return None
        suff = "(中)" if size == "中杯" else "(大)" if size == "大杯" else ""
        for cand in [f"{drink}{suff}", drink]:
            if cand in self.item_name_to_category: return cand
        return self.manual_aliases.get(drink)

    def resolve_swap_drink_candidates(self, base_keyword: str) -> List[str]:
        """Finds all menu items that match the base keyword exactly (excluding size) in the '飲品' category."""
        resolved_base = base_keyword
        if base_keyword in self.manual_aliases:
            resolved_base = self.manual_aliases[base_keyword]
            resolved_base = re.sub(r'\(.*\)', '', resolved_base).strip()

        candidates = []
        for name, category in self.item_name_to_category.items():
            name_no_size = re.sub(r'\(.*\)', '', name).strip()
            if category == "飲品" and name_no_size == resolved_base:
                candidates.append(name)
        
        # Fallback: if no exact base match, try contains (but this is rare with our menu)
        if not candidates:
            for name, category in self.item_name_to_category.items():
                if category == "飲品" and resolved_base in name:
                    candidates.append(name)
                    
        return sorted(list(set(candidates)))

    def choose_default_by_price(self, candidates: List[str], p_old: int) -> Tuple[Optional[str], int, bool]:
        """
        Chooses a default drink name from candidates based on p_old.
        Returns (chosen_name, delta, needs_size_confirm).
        """
        if not candidates:
            return None, 0, False

        price_map = {}
        for c in candidates:
            try:
                price_map[c] = menu_price_service.get_price("飲品", c)
            except KeyError:
                continue

        if not price_map:
            return None, 0, False

        # 1. Exact price match
        exact_matches = [name for name, price in price_map.items() if price == p_old]
        if exact_matches:
            # Prefer Medium if multiple exact matches, else shortest name
            chosen = sorted(exact_matches, key=lambda x: ("(中)" not in x, len(x)))[0]
            return chosen, 0, True

        # 2. Closest price <= p_old
        under_matches = [(name, price) for name, price in price_map.items() if price < p_old]
        if under_matches:
            under_matches.sort(key=lambda x: x[1], reverse=True)
            chosen = under_matches[0][0]
            return chosen, 0, True

        # 3. Cheapest price > p_old
        over_matches = [(name, price) for name, price in price_map.items() if price > p_old]
        if over_matches:
            over_matches.sort(key=lambda x: x[1])
            chosen = over_matches[0][0]
            delta = over_matches[0][1] - p_old
            return chosen, delta, True

        return None, 0, False

    def quote_combo_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        short = frame.get("combo_name")
        if not short or short not in self.combo_index: return {"status": "error", "message": f"找不到套餐：{short}"}
        data = self.combo_index[short]
        
        try:
            base = menu_price_service.get_price("套餐", data["full_name"])
        except KeyError:
            return {"status": "error", "message": f"無法取得套餐價格：{short}"}
            
        delta = 0
        swap = frame.get("swap_drink")
        if swap:
            old_can = data.get("default_drink_canonical")
            if not old_can: return {"status": "error", "message": f"{short} 沒有預設飲料，無法進行替換。"}
            try:
                old_p = menu_price_service.get_price("飲品", old_can)
                new_can = self.find_canonical_drink_name(swap.get("drink"), swap.get("size"))
                if not new_can: return {"status": "error", "message": f"菜單上找不到該飲品：{swap.get('drink')} {swap.get('size') or ''}"}
                new_p = menu_price_service.get_price("飲品", new_can)
                delta = max(0, new_p - old_p)
            except KeyError: return {"status": "error", "message": "計價時找不到品項價格。"}
        
        qty = frame.get("quantity", 1)
        total = (base + delta) * qty
        msg = f"{short} 價格為 {total}元"
        if delta > 0: msg += f" (含換飲料補差價 {delta}元)"
        return {"status": "success", "combo_name": short, "total_price": total, "message": msg}

    def _simplify_part(self, part: str) -> List[str]:
        clean = re.sub(r'\*\d+', '', part).strip()
        cands = [clean]
        ts = clean
        for t in self.remove_tokens: ts = ts.replace(t, "")
        ts = ts.strip()
        if ts not in cands: cands.append(ts)
        np = re.sub(r'\(.*\)', '', ts).strip()
        if np not in cands: cands.append(np)
        return cands

    def explode_combo_items(self, frame: Dict[str, Any]) -> List[Dict[str, Any]]:
        short = frame.get("combo_name")
        if not short or short not in self.combo_index: return []
        desc = self.combo_index[short]["desc"]
        parts = re.split(r'[+、]', desc)
        res = []
        for p in parts:
            p = p.strip()
            if not p: continue
            best = None
            cands = self._simplify_part(p)
            for c in cands:
                if c in self.simple_name_to_canonical:
                    best = self.simple_name_to_canonical[c]
                    break
            if best:
                cat = self.item_name_to_category.get(best)
                pf = {}
                if cat == "飯糰": pf = {"itemtype": "riceball", "flavor": best.replace("飯糰", "")}
                elif cat in ("吐司", "漢堡", "饅頭"): pf = {"itemtype": "carrier", "carrier": cat, "flavor": best.replace(cat, "")}
                elif cat == "飲品": 
                    sz, can = None, best
                    if "(中)" in can: sz, can = "中杯", can.replace("(中)", "")
                    elif "(大)" in can: sz, can = "大杯", can.replace("(大)", "")
                    pf = {"itemtype": "drink", "drink": can.strip(), "size": sz}
                elif cat == "蛋餅": pf = {"itemtype": "egg_pancake", "flavor": best.replace("蛋餅", "")}
                elif cat == "點心":
                    nm, qty = best, 1
                    m = re.search(r'\((\d+顆|\d+條|\d+個|\d+片)\)', nm)
                    if m:
                        qty = int(re.search(r'(\d+)', m.group(1)).group(1))
                        nm = nm.replace(m.group(0), "").strip()
                    pf = {"itemtype": "snack", "snack": nm, "quantity": qty}
                elif cat == "果醬吐司":
                    m = re.search(r'\(([^/]+)/(.+)\)', best)
                    if m: pf = {"itemtype": "jam_toast", "jam_toast": m.group(1).strip(), "size": m.group(2).strip().replace("片", "")}
                if pf:
                    pf["raw_text"] = best
                    res.append(pf)
        return res

combo_tool = ComboTool()