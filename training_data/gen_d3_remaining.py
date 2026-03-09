import json

SYS = "你是源飯糰的點餐機器人，只負責點餐。"

DRINK_T = {"type": "function", "function": {"name": "add_drink", "description": "加入飲料", "parameters": {"type": "object", "properties": {"flavor": {"type": "string"}, "size": {"type": "string", "enum": ["中杯", "大杯"]}, "temp": {"type": "string", "enum": ["冰", "溫", "熱"]}, "quantity": {"type": "integer"}, "customization": {"type": "string"}}, "required": ["flavor", "size", "temp"]}}}
CARRIER_T = {"type": "function", "function": {"name": "add_carrier", "description": "加入吐司/漢堡/饅頭", "parameters": {"type": "object", "properties": {"carrier": {"type": "string", "enum": ["吐司", "漢堡", "饅頭"]}, "flavor": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["carrier", "flavor"]}}}
EGG_T = {"type": "function", "function": {"name": "add_egg_pancake", "description": "加入蛋餅", "parameters": {"type": "object", "properties": {"flavor": {"type": "string"}, "quantity": {"type": "integer"}, "customization": {"type": "string"}}, "required": ["flavor"]}}}
SNACK_T = {"type": "function", "function": {"name": "add_snack", "description": "加入點心", "parameters": {"type": "object", "properties": {"flavor": {"type": "string"}, "quantity": {"type": "integer"}, "customization": {"type": "string"}}, "required": ["flavor"]}}}
RICEBALL_T = {"type": "function", "function": {"name": "add_riceball", "description": "加入飯糰", "parameters": {"type": "object", "properties": {"flavor": {"type": "string"}, "rice": {"type": "string", "enum": ["白米", "紫米", "混米"]}, "spicy": {"type": "boolean"}, "quantity": {"type": "integer"}, "customization": {"type": "string"}}, "required": ["flavor", "rice"]}}}
COMBO_T = {"type": "function", "function": {"name": "query_combo", "description": "查詢套餐內容", "parameters": {"type": "object", "properties": {"combo_name": {"type": "string"}}, "required": ["combo_name"]}}}
FINALIZE_T = {"type": "function", "function": {"name": "finalize_order", "description": "結帳", "parameters": {"type": "object", "properties": {"dine_type": {"type": "string"}, "payment_method": {"type": "string"}}, "required": ["dine_type", "payment_method"]}}}

def tc(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}

def tr(cid, obj):
    return {"role": "tool", "content": json.dumps(obj, ensure_ascii=False), "tool_call_id": cid}

lines = []
n = 324

# ============ FOOD SLANG (10 lines) ============

# 26: 吐司加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"吐司加蛋一份"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_carrier",{"carrier":"吐司","flavor":"煎蛋"})]},
     tr("call_1",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 煎蛋吐司","cart_count":1}),
     {"role":"assistant","content":"好，煎蛋吐司～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":25,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 25 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 27: 吐司加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"來一份吐司加蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_carrier",{"carrier":"吐司","flavor":"煎蛋"})]},
     tr("call_1",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 煎蛋吐司","cart_count":1}),
     {"role":"assistant","content":"好，煎蛋吐司～還要什麼嗎？"},
     {"role":"user","content":"不用 內用 Line Pay"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":25,"item_count":1,"dine_type":"dine-in","payment_method":"line_pay"}),
     {"role":"assistant","content":f"好，總共 25 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 28: 蔬菜蛋餅
m = [{"role":"system","content":SYS},{"role":"user","content":"蔬菜蛋餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_egg_pancake",{"flavor":"高麗菜"})]},
     tr("call_1",{"ok":True,"item_id":"egg_pancake_1","message":"已加入 1份 高麗菜蛋餅","cart_count":1}),
     {"role":"assistant","content":"好，高麗菜蛋餅～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 付現"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":30,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 30 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[EGG_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 29: 蔬菜蛋餅
m = [{"role":"system","content":SYS},{"role":"user","content":"我要一份蔬菜蛋餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_egg_pancake",{"flavor":"高麗菜"})]},
     tr("call_1",{"ok":True,"item_id":"egg_pancake_1","message":"已加入 1份 高麗菜蛋餅","cart_count":1}),
     {"role":"assistant","content":"好，高麗菜蛋餅～還要別的嗎？"},
     {"role":"user","content":"不用了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":30,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 30 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[EGG_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 30: 抓餅
m = [{"role":"system","content":SYS},{"role":"user","content":"一份抓餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_snack",{"flavor":"蔥抓餅(原味)"})]},
     tr("call_1",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(原味)","cart_count":1}),
     {"role":"assistant","content":"好，蔥抓餅～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":30,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 30 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 31: 抓餅
m = [{"role":"system","content":SYS},{"role":"user","content":"給我抓餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_snack",{"flavor":"蔥抓餅(原味)"})]},
     tr("call_1",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(原味)","cart_count":1}),
     {"role":"assistant","content":"好，蔥抓餅～還要什麼嗎？"},
     {"role":"user","content":"好了 內用 付現"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"內用","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":30,"item_count":1,"dine_type":"dine-in","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 30 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 32: 抓餅加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"抓餅加蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_snack",{"flavor":"蔥抓餅(加蛋)"})]},
     tr("call_1",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(加蛋)","cart_count":1}),
     {"role":"assistant","content":"好，蔥抓餅加蛋～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":40,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 40 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 33: 抓餅加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"來一份抓餅加蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_snack",{"flavor":"蔥抓餅(加蛋)"})]},
     tr("call_1",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(加蛋)","cart_count":1}),
     {"role":"assistant","content":"好，蔥抓餅加蛋～還要什麼嗎？"},
     {"role":"user","content":"這樣就好 外帶 Line Pay"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":40,"item_count":1,"dine_type":"take-out","payment_method":"line_pay"}),
     {"role":"assistant","content":f"好，總共 40 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 34: 豬排蛋堡
m = [{"role":"system","content":SYS},{"role":"user","content":"豬排蛋堡一個"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_carrier",{"carrier":"漢堡","flavor":"醬燒肉片蛋"})]},
     tr("call_1",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 醬燒肉片蛋漢堡","cart_count":1}),
     {"role":"assistant","content":"好，醬燒肉片蛋漢堡～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":50,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 50 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 35: 漢堡肉吐司
m = [{"role":"system","content":SYS},{"role":"user","content":"漢堡肉吐司"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_carrier",{"carrier":"吐司","flavor":"豬肉蛋"})]},
     tr("call_1",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 豬肉蛋吐司","cart_count":1}),
     {"role":"assistant","content":"好，豬肉蛋吐司～還需要什麼嗎？"},
     {"role":"user","content":"不用 外帶 付現"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":40,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 40 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# ============ AMBIGUITY (10 lines) ============

# 36: 肉鬆飯糰(1) - 傳統
m = [{"role":"system","content":SYS},{"role":"user","content":"肉鬆飯糰"},
     {"role":"assistant","content":"肉鬆飯糰是傳統的還是只包肉鬆？"},
     {"role":"user","content":"傳統的"},
     {"role":"assistant","content":"好，白米紫米還是混米？"},
     {"role":"user","content":"紫米"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_riceball",{"flavor":"源味傳統","rice":"紫米"})]},
     tr("call_1",{"ok":True,"item_id":"riceball_1","message":"已加入 1份 紫米源味傳統","cart_count":1}),
     {"role":"assistant","content":"好，傳統紫米飯糰～要加辣菜脯嗎？"},
     {"role":"user","content":"不用"},
     {"role":"assistant","content":"好～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":45,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 45 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[RICEBALL_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 37: 肉鬆飯糰(2) - 只包肉鬆
m = [{"role":"system","content":SYS},{"role":"user","content":"我要肉鬆飯糰"},
     {"role":"assistant","content":"肉鬆飯糰是傳統的還是只包肉鬆？"},
     {"role":"user","content":"只包肉鬆就好"},
     {"role":"assistant","content":"好，白米紫米還是混米？"},
     {"role":"user","content":"混米"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_riceball",{"flavor":"肉鬆","rice":"混米"})]},
     tr("call_1",{"ok":True,"item_id":"riceball_1","message":"已加入 1份 混米肉鬆","cart_count":1}),
     {"role":"assistant","content":"好，混米肉鬆飯糰～還需要什麼嗎？"},
     {"role":"user","content":"沒了 內用 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"內用","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":35,"item_count":1,"dine_type":"dine-in","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 35 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[RICEBALL_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 38: 套餐一(1) - 歧義
m = [{"role":"system","content":SYS},{"role":"user","content":"套餐一"},
     {"role":"assistant","content":"套餐一有飯糰套餐跟蛋餅套餐，要哪一種？"},
     {"role":"user","content":"飯糰的"},
     {"role":"assistant","content":"好，飯糰要什麼口味？白米紫米混米？"},
     {"role":"user","content":"鮪魚 白米"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_riceball",{"flavor":"鮪魚","rice":"白米"})]},
     tr("call_1",{"ok":True,"item_id":"riceball_1","message":"已加入 1份 白米鮪魚","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"溫"})]},
     tr("call_2",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯溫有糖豆漿","cart_count":2}),
     {"role":"assistant","content":"好，鮪魚白米飯糰配中杯溫豆漿～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":65,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 65 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[RICEBALL_T,DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 39: 套餐E(2)
m = [{"role":"system","content":SYS},{"role":"user","content":"套餐E"},
     {"role":"assistant","content":"套餐E有飯糰套餐跟蛋餅套餐，要哪一種？"},
     {"role":"user","content":"蛋餅"},
     {"role":"assistant","content":"好，蛋餅要什麼口味？"},
     {"role":"user","content":"玉米"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_egg_pancake",{"flavor":"玉米"})]},
     tr("call_1",{"ok":True,"item_id":"egg_pancake_1","message":"已加入 1份 玉米蛋餅","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_drink",{"flavor":"精選紅茶","size":"中杯","temp":"冰"})]},
     tr("call_2",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯冰精選紅茶","cart_count":2}),
     {"role":"assistant","content":"好，玉米蛋餅配中杯冰紅茶～還需要什麼嗎？"},
     {"role":"user","content":"不用 外帶 付現"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":55,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 55 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[EGG_T,DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 40: 豆漿有糖無糖(1)
m = [{"role":"system","content":SYS},{"role":"user","content":"豆漿 大杯冰的"},
     {"role":"assistant","content":"有糖還是無糖？"},
     {"role":"user","content":"有糖"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰有糖豆漿","cart_count":1}),
     {"role":"assistant","content":"好，大杯冰豆漿～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":30,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 30 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 41: 豆漿有糖無糖(2)
m = [{"role":"system","content":SYS},{"role":"user","content":"來杯豆漿 中杯溫的"},
     {"role":"assistant","content":"有糖還是無糖？"},
     {"role":"user","content":"無糖"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"無糖豆漿","size":"中杯","temp":"溫"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯溫無糖豆漿","cart_count":1}),
     {"role":"assistant","content":"好，中杯溫無糖豆漿～還要什麼嗎？"},
     {"role":"user","content":"不用了 外帶 Line Pay"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":20,"item_count":1,"dine_type":"take-out","payment_method":"line_pay"}),
     {"role":"assistant","content":f"好，總共 20 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 42: 奶(1) - 歧義
m = [{"role":"system","content":SYS},{"role":"user","content":"一杯奶"},
     {"role":"assistant","content":"是奶茶還是牛奶？"},
     {"role":"user","content":"奶茶 大杯冰的"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰純鮮奶茶","cart_count":1}),
     {"role":"assistant","content":"好，大杯冰奶茶～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":55,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 55 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 43: 蛋(1) - 歧義
m = [{"role":"system","content":SYS},{"role":"user","content":"加一個蛋"},
     {"role":"assistant","content":"是荷包蛋還是蛋餅？"},
     {"role":"user","content":"荷包蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_snack",{"flavor":"荷包蛋"})]},
     tr("call_1",{"ok":True,"item_id":"snack_1","message":"已加入 1份 荷包蛋","cart_count":1}),
     {"role":"assistant","content":"好，荷包蛋～還需要什麼嗎？"},
     {"role":"user","content":"沒了 內用 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"內用","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":15,"item_count":1,"dine_type":"dine-in","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 15 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 44: 米漿(1) - 歧義
m = [{"role":"system","content":SYS},{"role":"user","content":"米漿一杯"},
     {"role":"assistant","content":"花生糙米漿還是米漿加豆漿？"},
     {"role":"user","content":"花生糙米漿 大杯溫的"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"花生糙米漿","size":"大杯","temp":"溫"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯溫花生糙米漿","cart_count":1}),
     {"role":"assistant","content":"好，大杯溫花生糙米漿～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":35,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 35 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 45: 紅茶拿鐵vs奶茶(1)
m = [{"role":"system","content":SYS},{"role":"user","content":"紅茶拿鐵 大杯冰的"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"紅茶拿鐵","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰紅茶拿鐵","cart_count":1}),
     {"role":"assistant","content":"好，大杯冰紅茶拿鐵～還需要什麼嗎？"},
     {"role":"user","content":"不用 外帶 付現"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_2",{"ok":True,"order_number":n,"total":55,"item_count":1,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 55 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# ============ COMBO SLANG (10 lines) ============

# 46: 大冰奶 蔬菜蛋餅
m = [{"role":"system","content":SYS},{"role":"user","content":"大冰奶 蔬菜蛋餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰純鮮奶茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_egg_pancake",{"flavor":"高麗菜"})]},
     tr("call_2",{"ok":True,"item_id":"egg_pancake_1","message":"已加入 1份 高麗菜蛋餅","cart_count":2}),
     {"role":"assistant","content":"好，大杯冰奶茶跟高麗菜蛋餅～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":85,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 85 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,EGG_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 47: 中溫豆 抓餅加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"中溫豆 抓餅加蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"溫"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯溫有糖豆漿","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_snack",{"flavor":"蔥抓餅(加蛋)"})]},
     tr("call_2",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(加蛋)","cart_count":2}),
     {"role":"assistant","content":"好，中杯溫豆漿跟蔥抓餅加蛋～還需要什麼嗎？"},
     {"role":"user","content":"不用了 外帶 Line Pay"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":65,"item_count":2,"dine_type":"take-out","payment_method":"line_pay"}),
     {"role":"assistant","content":f"好，總共 65 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 48: 大冰紅 吐司加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"大冰紅 吐司加蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰精選紅茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_carrier",{"carrier":"吐司","flavor":"煎蛋"})]},
     tr("call_2",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 煎蛋吐司","cart_count":2}),
     {"role":"assistant","content":"好，大杯冰紅茶跟煎蛋吐司～還要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":55,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 55 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 49: 中冰紅 黑椒麵
m = [{"role":"system","content":SYS},{"role":"user","content":"中冰紅 黑椒麵"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"精選紅茶","size":"中杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯冰精選紅茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_snack",{"flavor":"黑椒鐵板麵"})]},
     tr("call_2",{"ok":True,"item_id":"snack_1","message":"已加入 1份 黑椒鐵板麵","cart_count":2}),
     {"role":"assistant","content":"好，中杯冰紅茶跟黑椒鐵板麵～還需要什麼嗎？"},
     {"role":"user","content":"不用 內用 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"內用","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":80,"item_count":2,"dine_type":"dine-in","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 80 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 50: 大冰奶 豬排蛋堡
m = [{"role":"system","content":SYS},{"role":"user","content":"大冰奶 豬排蛋堡"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰純鮮奶茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_carrier",{"carrier":"漢堡","flavor":"醬燒肉片蛋"})]},
     tr("call_2",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 醬燒肉片蛋漢堡","cart_count":2}),
     {"role":"assistant","content":"好，大杯冰奶茶跟醬燒肉片蛋漢堡～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 付現"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":105,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 105 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 51: 大冰紅 蔬菜蛋餅 加辣
m = [{"role":"system","content":SYS},{"role":"user","content":"大冰紅 蔬菜蛋餅 加辣"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰精選紅茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_egg_pancake",{"flavor":"高麗菜","customization":"加辣"})]},
     tr("call_2",{"ok":True,"item_id":"egg_pancake_1","message":"已加入 1份 高麗菜蛋餅(加辣)","cart_count":2}),
     {"role":"assistant","content":"好，大杯冰紅茶跟高麗菜蛋餅加辣～還要什麼嗎？"},
     {"role":"user","content":"這樣 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":60,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 60 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,EGG_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 52: 清漿中溫 漢堡肉吐司
m = [{"role":"system","content":SYS},{"role":"user","content":"清漿中溫 漢堡肉吐司"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"無糖豆漿","size":"中杯","temp":"溫"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯溫無糖豆漿","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_carrier",{"carrier":"吐司","flavor":"豬肉蛋"})]},
     tr("call_2",{"ok":True,"item_id":"carrier_1","message":"已加入 1份 豬肉蛋吐司","cart_count":2}),
     {"role":"assistant","content":"好，中杯溫無糖豆漿跟豬肉蛋吐司～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":60,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 60 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,CARRIER_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 53: 大冰豆 抓餅
m = [{"role":"system","content":SYS},{"role":"user","content":"大冰豆 一份抓餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯冰有糖豆漿","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_snack",{"flavor":"蔥抓餅(原味)"})]},
     tr("call_2",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(原味)","cart_count":2}),
     {"role":"assistant","content":"好，大杯冰豆漿跟蔥抓餅～還要什麼嗎？"},
     {"role":"user","content":"不用 內用 Line Pay"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":60,"item_count":2,"dine_type":"dine-in","payment_method":"line_pay"}),
     {"role":"assistant","content":f"好，總共 60 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 54: 大溫奶 玉米蛋餅
m = [{"role":"system","content":SYS},{"role":"user","content":"大溫奶 玉米蛋餅"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"溫"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 大杯溫純鮮奶茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_egg_pancake",{"flavor":"玉米"})]},
     tr("call_2",{"ok":True,"item_id":"egg_pancake_1","message":"已加入 1份 玉米蛋餅","cart_count":2}),
     {"role":"assistant","content":"好，大杯溫奶茶跟玉米蛋餅～還需要什麼嗎？"},
     {"role":"user","content":"沒了 外帶 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":90,"item_count":2,"dine_type":"take-out","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 90 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,EGG_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# 55: 中冰奶 抓餅加蛋
m = [{"role":"system","content":SYS},{"role":"user","content":"中冰奶 抓餅加蛋"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_1","add_drink",{"flavor":"純鮮奶茶","size":"中杯","temp":"冰"})]},
     tr("call_1",{"ok":True,"item_id":"drink_1","message":"已加入 1份 中杯冰純鮮奶茶","cart_count":1}),
     {"role":"assistant","content":None,"tool_calls":[tc("call_2","add_snack",{"flavor":"蔥抓餅(加蛋)"})]},
     tr("call_2",{"ok":True,"item_id":"snack_1","message":"已加入 1份 蔥抓餅(加蛋)","cart_count":2}),
     {"role":"assistant","content":"好，中杯冰奶茶跟蔥抓餅加蛋～還需要什麼嗎？"},
     {"role":"user","content":"不用了 內用 現金"},
     {"role":"assistant","content":None,"tool_calls":[tc("call_3","finalize_order",{"dine_type":"內用","payment_method":"現金"})]},
     tr("call_3",{"ok":True,"order_number":n,"total":85,"item_count":2,"dine_type":"dine-in","payment_method":"cash"}),
     {"role":"assistant","content":f"好，總共 85 元，取餐號碼 {n} 號，謝謝！"}]
lines.append(json.dumps({"messages":m,"tools":[DRINK_T,SNACK_T,FINALIZE_T]},ensure_ascii=False)); n+=1

# Write all
with open(r"C:\Users\User\Desktop\ai-ordering-system\training_data\category_d3_slang.jsonl", "a", encoding="utf-8") as f:
    for l in lines:
        f.write(l + "\n")

print(f"Appended {len(lines)} lines (food+ambiguity+combo)")
