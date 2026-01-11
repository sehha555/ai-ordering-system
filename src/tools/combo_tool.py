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
        self.combo_index = {}  # Maps short combo name (e.g., "套餐一") to {price, description_string, full_name}
        
        # Build reverse index for parsing sub-items from description_string
        # Maps canonical item name to its category
        self.item_name_to_category = {item['name']: item['category'] for item in all_items if 'name' in item and 'category' in item}
        self.all_item_names = sorted(list(self.item_name_to_category.keys()), key=len, reverse=True)

        # Create a mapping from simplified names to canonical names
        self.simple_name_to_canonical = {}
        
        # Load manual aliases from config
        self.manual_aliases = self.alias_cfg.get("manual_aliases", {})
        
        # Load normalization rules
        norm_rules = self.alias_cfg.get("normalize_rules", {})
        remove_tokens = norm_rules.get("remove_tokens", [])
        regex_removals = norm_rules.get("regex_removals", [])

        for name in self.all_item_names:
            # Create a simplified version of the name for matching
            simplified = name
            for token in remove_tokens:
                simplified = simplified.replace(token, "")
            
            for pattern in regex_removals:
                simplified = re.sub(pattern, '', simplified)
            
            simplified = simplified.strip()
            self.simple_name_to_canonical[simplified] = name
            
            # Also map the name without just the parens, if different (fallback logic from original code, mostly covered by regex but kept for safety)
            simplified_no_parens = re.sub(r'\(.*\)', '', name).strip()
            if simplified_no_parens != simplified:
                self.simple_name_to_canonical[simplified_no_parens] = name

        # Integrate manual aliases into simple_name_to_canonical if not present (or overwrite/prioritize)
        for alias, canonical in self.manual_aliases.items():
            # Only add if the canonical exists in menu (safety check)
            if canonical in self.item_name_to_category:
                self.simple_name_to_canonical[alias] = canonical
            else:
                 print(f"Warning: Alias target '{canonical}' for '{alias}' not found in menu. Ignoring.")

        # Build reverse index for combo detection by content (maps sub-item name to list of short combo names)
        # Key: Simplified Name (as likely spoken by user or in combo description)
        self.sub_item_to_combo_names = {} 

        for item in all_items:
            if item.get("category") == "套餐":
                full_combo_name = item.get("name") # e.g., "套餐一 醬燒肉片蛋餅+豆漿(大)"
                
                if not full_combo_name or "price" not in item:
                    continue

                # Try to extract the simple combo name (e.g., "套餐一", "兒童餐")
                match = re.match(r"^(套餐[一二三四五六七八九十ABCDE]|兒童餐)\s*(.*)", full_combo_name)
                if not match:
                    continue
                
                combo_name_short = match.group(1) # e.g., "套餐一"
                description_string = match.group(2).strip() # e.g., "醬燒肉片蛋餅+豆漿(大)"

                self.combo_index[combo_name_short] = {
                    "price": item["price"],
                    "description_string": description_string,
                    "full_name": full_combo_name
                }

                # Populate sub_item_to_combo_names
                # We check which simplified names are present in the description string
                temp_description = description_string
                
                # Iterate over simple_name_to_canonical to find matches
                # Sort keys by length to match longest first
                sorted_simple_names = sorted(self.simple_name_to_canonical.keys(), key=len, reverse=True)
                
                for simple_name in sorted_simple_names:
                    if simple_name in temp_description:
                        if simple_name not in self.sub_item_to_combo_names:
                            self.sub_item_to_combo_names[simple_name] = []
                        if combo_name_short not in self.sub_item_to_combo_names[simple_name]:
                            self.sub_item_to_combo_names[simple_name].append(combo_name_short)
                        
                        temp_description = temp_description.replace(simple_name, "", 1)


    def parse_combo_utterance(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parses an utterance to find a combo order.
        Returns a combo frame if a unique combo is identified, otherwise None.
        """
        # 1. Direct match by short combo name (e.g., "套餐一", "兒童餐")
        for combo_name_short in self.combo_index:
            if combo_name_short in text:
                return {
                    "itemtype": "combo",
                    "combo_name": combo_name_short,
                    "quantity": 1,  # 暫時預設數量為 1
                    "raw_text": text,
                }

        # 2. Match by content (e.g., "我要鮪魚飯糰跟豆漿")
        found_sub_items_in_text = [
            item_name for item_name in self.sub_item_to_combo_names if item_name in text
        ]
        
        if not found_sub_items_in_text:
            return None

        # Guard: If only one item matched, and it exists as a standalone product, 
        # prefer the standalone product (return None so router handles it).
        if len(found_sub_items_in_text) == 1:
            simple_name = found_sub_items_in_text[0]
            allow_single_list = self.alias_cfg.get("allow_single_item_keywords", [])
            
            # Check config whitelist OR dynamic existence
            if simple_name in allow_single_list or simple_name in self.simple_name_to_canonical:
                return None

        # Find potential combos that include all the found items
        possible_combos = set()
        if found_sub_items_in_text:
            # Start with combos from the first found item
            possible_combos.update(self.sub_item_to_combo_names.get(found_sub_items_in_text[0], []))
            # Intersect with combos from subsequent found items
            for i in range(1, len(found_sub_items_in_text)):
                possible_combos.intersection_update(self.sub_item_to_combo_names.get(found_sub_items_in_text[i], []))

        # If we uniquely identify one combo, return it
        if len(possible_combos) == 1:
            combo_name_short = possible_combos.pop()
            return {
                "itemtype": "combo",
                "combo_name": combo_name_short,
                "quantity": 1,
                "raw_text": text,
            }

        return None

    def quote_combo_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """
        Quotes the price for a given combo frame.
        """
        combo_name_short = frame.get("combo_name")
        if not combo_name_short or combo_name_short not in self.combo_index:
            return {"status": "error", "message": f"找不到套餐：{combo_name_short}"}

        full_name = self.combo_index[combo_name_short].get("full_name")
        try:
            price = menu_price_service.get_price("套餐", full_name)
        except KeyError:
            return {"status": "error", "message": f"無法取得套餐價格：{combo_name_short}"}

        quantity = frame.get("quantity", 1)
        return {
            "status": "success",
            "combo_name": combo_name_short,
            "total_price": int(price) * quantity,
            "message": f"{combo_name_short} 價格為 {price}元"
        }

    def explode_combo_items(self, frame: Dict[str, Any]) -> List[Dict[str, Any]]:
        combo_name_short = frame.get("combo_name")
        if not combo_name_short or combo_name_short not in self.combo_index:
            return []
        
        description_string = self.combo_index[combo_name_short]["description_string"]
        
        parts = re.split(r'[+、]', description_string) # Split by '+' or '、'
        sub_item_frames = []

        for part in parts:
            part = part.strip()
            if not part: continue

            # Try to match a known menu item name within this part
            best_match_item_name = None
            
            # Simplify the part to match the keys in simple_name_to_canonical
            simplified_part = re.sub(r'\(.*\)', '', part).strip()

            if simplified_part in self.simple_name_to_canonical:
                best_match_item_name = self.simple_name_to_canonical[simplified_part]
            
            if best_match_item_name:
                category = self.item_name_to_category.get(best_match_item_name)
                partial_frame = {}
                
                # Create partial frames based on category
                if category == "飯糰":
                    partial_frame = {"itemtype": "riceball", "flavor": best_match_item_name.replace("飯糰", "")}
                elif category in ("吐司", "漢堡", "饅頭"):
                    partial_frame = {"itemtype": "carrier", "carrier": category, "flavor": best_match_item_name.replace(category, "")}
                elif category == "飲品": 
                    # Handle size and clean up drink names
                    size = None
                    drink_name_raw = best_match_item_name
                    if "(中)" in drink_name_raw:
                        size = "中杯"
                        drink_name_raw = drink_name_raw.replace("(中)", "")
                    elif "(大)" in drink_name_raw:
                        size = "大杯"
                        drink_name_raw = drink_name_raw.replace("(大)", "")
                    
                    # Clean up common prefixes/suffixes
                    drink_name_cleaned = drink_name_raw.replace("有糖", "").replace("無糖", "").replace("精選", "").replace("純", "").replace("黑糖", "").replace("+豆漿", "").replace("清香", "").replace("純鮮奶", "").replace("咖啡", "").replace("茶", "")
                    # Special handling for "紅茶+豆漿" -> "紅茶豆漿"
                    if "紅茶+豆漿" in best_match_item_name:
                        drink_name_cleaned = "紅茶豆漿"
                    elif "米漿+豆漿" in best_match_item_name:
                        drink_name_cleaned = "米漿豆漿"

                    partial_frame = {"itemtype": "drink", "drink": drink_name_cleaned.strip(), "size": size}
                elif category == "蛋餅":
                    partial_frame = {"itemtype": "egg_pancake", "flavor": best_match_item_name.replace("蛋餅", "")}
                elif category == "點心":
                    # Some snacks have quantities, e.g., "煎餃(8顆)". Need to handle.
                    snack_name_cleaned = best_match_item_name
                    qty_match = re.search(r'\((\d+顆|\d+條|\d+個|\d+片)\)', snack_name_cleaned)
                    quantity = 1
                    if qty_match:
                        qty_str = qty_match.group(1)
                        num_match = re.search(r'(\d+)', qty_str)
                        if num_match:
                            quantity = int(num_match.group(1))
                        snack_name_cleaned = snack_name_cleaned.replace(qty_match.group(0), "").strip()
                    
                    partial_frame = {"itemtype": "snack", "snack": snack_name_cleaned, "quantity": quantity}
                elif category == "果醬吐司":
                    # Fruit jam toast has flavor and thickness, e.g. "果醬吐司(草莓/薄片)"
                    jam_toast_name_raw = best_match_item_name
                    flavor_match = re.search(r'\(([^/]+)/(.+)\)', jam_toast_name_raw)
                    flavor = None
                    thickness = None
                    if flavor_match:
                        flavor = flavor_match.group(1).strip()
                        thickness = flavor_match.group(2).strip().replace("片", "") # Remove '片'
                    
                    partial_frame = {"itemtype": "jam_toast", "jam_toast": flavor, "size": thickness}
                
                # Add other categories as needed
                if partial_frame:
                    partial_frame["raw_text"] = best_match_item_name # Store original name for context
                    sub_item_frames.append(partial_frame)
            else:
                print(f"Warning: Could not parse sub-item '{part}' from combo description string: '{description_string}'.")
        
        return sub_item_frames

# Instantiate a singleton
combo_tool = ComboTool()
