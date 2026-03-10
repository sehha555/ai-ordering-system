"""訓練資料品質驗證 — 菜單一致性 + Schema + 執行驗證"""
import json
import sys
from pathlib import Path
from collections import Counter

MENU_PATH = Path(__file__).parent.parent / "src" / "tools" / "menu" / "menu_all.json"
DATA_PATH = Path(__file__).parent / "all_training_data.jsonl"

# ── 從菜單建立合法值 ──────────────────────────

with open(MENU_PATH, encoding="utf-8-sig") as f:
    menu = json.load(f)

# 按 category 收集品名
menu_by_cat: dict[str, set[str]] = {}
for item in menu:
    cat = item.get("category", "")
    name = item.get("name", "")
    menu_by_cat.setdefault(cat, set()).add(name)

# 飯糰口味
RICEBALL_FLAVORS = menu_by_cat.get("飯糰", set())
# 蛋餅口味（去掉「蛋餅」後綴）
EGG_PANCAKE_FLAVORS = {n.replace("蛋餅", "") for n in menu_by_cat.get("蛋餅", set())}
# 飲料品名
DRINK_FLAVORS = menu_by_cat.get("飲品", set())
# 載體配料（吐司/漢堡類）
CARRIER_FLAVORS = set()
for cat in ["吐司", "漢堡", "饅頭蛋"]:
    for n in menu_by_cat.get(cat, set()):
        # 去掉載體名稱
        for suffix in ["吐司", "漢堡", "饅頭"]:
            n = n.replace(suffix, "")
        CARRIER_FLAVORS.add(n.strip())
# 點心品名
SNACK_FLAVORS = set()
for cat in ["點心", "鐵板麵", "果醬吐司", "蔥抓餅"]:
    SNACK_FLAVORS.update(menu_by_cat.get(cat, set()))

# 合法 enum 值
VALID_RICE = {"白米", "紫米", "混米"}
VALID_SIZE = {"中杯", "大杯"}
VALID_TEMP = {"冰", "溫", "熱"}
VALID_CARRIER = {"吐司", "漢堡", "饅頭"}
VALID_BUN_TYPE = {"黑糖", "白", "芋頭", "黑花捲", "白花捲", "南瓜"}

# ── Schema 定義（required fields）──────────────

TOOL_SCHEMA = {
    "add_riceball": {"required": ["flavor", "rice"], "optional": ["spicy", "quantity", "customization"]},
    "add_egg_pancake": {"required": ["flavor"], "optional": ["quantity", "customization"]},
    "add_drink": {"required": ["flavor", "size", "temp"], "optional": ["quantity", "customization"]},
    "add_carrier": {"required": ["flavor", "carrier"], "optional": ["bun_type", "quantity", "customization"]},
    "add_snack": {"required": ["flavor"], "optional": ["quantity", "customization"]},
    "add_combo": {"required": ["combo_name"], "optional": ["riceball_flavor", "rice", "drink_flavor", "drink_size", "drink_temp", "quantity", "customization"]},
    "remove_from_cart": {"required": ["item_id"], "optional": []},
    "query_menu": {"required": [], "optional": ["category"]},
    "finalize_order": {"required": ["dine_type", "payment_method"], "optional": []},
}

# ── 驗證 ──────────────────────────────────────

errors: list[str] = []
warnings: list[str] = []
stats = Counter()

with open(DATA_PATH, encoding="utf-8") as f:
    lines = f.readlines()

for line_num, line in enumerate(lines, 1):
    line = line.strip()
    if not line:
        continue

    # 1. JSON 格式
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        errors.append(f"L{line_num}: JSON parse error: {e}")
        continue

    stats["total"] += 1

    # 2. 基本結構
    if "messages" not in obj:
        errors.append(f"L{line_num}: missing 'messages'")
        continue
    if "tools" not in obj:
        errors.append(f"L{line_num}: missing 'tools'")

    # 3. System message
    msgs = obj["messages"]
    if not msgs or msgs[0].get("role") != "system":
        errors.append(f"L{line_num}: first message not system")
    elif msgs[0].get("content") != "你是源飯糰的點餐機器人，只負責點餐。":
        warnings.append(f"L{line_num}: non-standard system prompt")

    # 4. Tool calls 驗證
    has_finalize = False
    for msg in msgs:
        if msg.get("role") != "assistant" or "tool_calls" not in msg:
            continue
        tcs = msg["tool_calls"]
        if not tcs:
            continue

        # content 應該是 null
        if msg.get("content") is not None:
            warnings.append(f"L{line_num}: assistant with tool_calls has content != null: {msg.get('content')[:30]}...")

        for tc in tcs:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            stats[f"tool:{name}"] += 1

            # arguments 必須是 dict
            if isinstance(args, str):
                errors.append(f"L{line_num}: {name} arguments is string!")
                try:
                    args = json.loads(args)
                except:
                    continue

            if name == "finalize_order":
                has_finalize = True

            # Schema 驗證
            schema = TOOL_SCHEMA.get(name)
            if not schema:
                errors.append(f"L{line_num}: unknown tool '{name}'")
                continue

            for req in schema["required"]:
                if req not in args:
                    errors.append(f"L{line_num}: {name} missing required '{req}'")

            all_fields = schema["required"] + schema["optional"]
            for key in args:
                if key not in all_fields:
                    warnings.append(f"L{line_num}: {name} unexpected field '{key}'")

            # Enum 驗證
            if name == "add_riceball":
                if "rice" in args and args["rice"] not in VALID_RICE:
                    errors.append(f"L{line_num}: invalid rice '{args['rice']}'")
                if "spicy" in args and not isinstance(args["spicy"], bool):
                    warnings.append(f"L{line_num}: spicy should be bool, got {type(args['spicy']).__name__}")

            elif name == "add_drink":
                if "size" in args and args["size"] not in VALID_SIZE:
                    errors.append(f"L{line_num}: invalid size '{args['size']}'")
                if "temp" in args and args["temp"] not in VALID_TEMP:
                    errors.append(f"L{line_num}: invalid temp '{args['temp']}'")

            elif name == "add_carrier":
                if "carrier" in args and args["carrier"] not in VALID_CARRIER:
                    errors.append(f"L{line_num}: invalid carrier '{args['carrier']}'")
                if "bun_type" in args and args["bun_type"] not in VALID_BUN_TYPE:
                    warnings.append(f"L{line_num}: unusual bun_type '{args['bun_type']}'")

    if not has_finalize:
        stats["no_finalize"] += 1

# ── 報告 ──────────────────────────────────────

print("=" * 60)
print(f"訓練資料品質驗證報告")
print(f"總筆數: {stats['total']}")
print("=" * 60)

print(f"\n❌ 錯誤 ({len(errors)}):")
if errors:
    for e in errors[:50]:  # 最多顯示 50 個
        print(f"  {e}")
    if len(errors) > 50:
        print(f"  ... 還有 {len(errors) - 50} 個錯誤")
else:
    print("  無錯誤！")

print(f"\n⚠️ 警告 ({len(warnings)}):")
if warnings:
    for w in warnings[:30]:
        print(f"  {w}")
    if len(warnings) > 30:
        print(f"  ... 還有 {len(warnings) - 30} 個警告")
else:
    print("  無警告！")

print(f"\n📊 統計:")
print(f"  無 finalize_order: {stats.get('no_finalize', 0)} 筆")
print(f"\n  Tool 使用次數:")
for key, val in sorted(stats.items()):
    if key.startswith("tool:"):
        print(f"    {key[5:]}: {val}")

print(f"\n✅ 結論: {len(errors)} 錯誤, {len(warnings)} 警告")
