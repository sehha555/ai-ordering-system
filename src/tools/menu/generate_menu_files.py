import json, os
from collections import defaultdict

menu_dir = r"src\tools\menu"
with open(os.path.join(menu_dir, "menu_all.json"), "r", encoding="utf-8") as f:
    items = json.load(f)

by_cat = defaultdict(list)
for it in items:
    by_cat[it["category"]].append(it)

# types.json
types = sorted(by_cat.keys())
with open(os.path.join(menu_dir, "types.json"), "w", encoding="utf-8") as f:
    json.dump(types, f, ensure_ascii=False, indent=2)

# items_<category>.json
for cat, arr in by_cat.items():
    arr = sorted(arr, key=lambda x: (x["price"], x["name"]))
    safe = cat.replace("/", "_")
    out = os.path.join(menu_dir, f"items_{safe}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)

print("OK: generated", len(types), "categories and", sum(len(v) for v in by_cat.values()), "items")
