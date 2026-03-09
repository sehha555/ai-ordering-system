import json

SYSTEM = "你是源飯糰的點餐機器人，只負責點餐。"

T_RICEBALL = {"type":"function","function":{"name":"add_riceball","description":"加入飯糰","parameters":{"type":"object","properties":{"flavor":{"type":"string"},"rice":{"type":"string","enum":["白米","紫米","混米"]},"spicy":{"type":"boolean"},"quantity":{"type":"integer"},"customization":{"type":"string"}},"required":["flavor","rice"]}}}
T_DRINK = {"type":"function","function":{"name":"add_drink","description":"加入飲料","parameters":{"type":"object","properties":{"flavor":{"type":"string"},"size":{"type":"string","enum":["中杯","大杯"]},"temp":{"type":"string","enum":["冰","溫","熱"]},"quantity":{"type":"integer"},"customization":{"type":"string"}},"required":["flavor","size","temp"]}}}
T_CARRIER = {"type":"function","function":{"name":"add_carrier","description":"加入吐司/漢堡/饅頭","parameters":{"type":"object","properties":{"carrier":{"type":"string","enum":["吐司","漢堡","饅頭"]},"flavor":{"type":"string"},"quantity":{"type":"integer"},"customization":{"type":"string"}},"required":["carrier","flavor"]}}}
T_EGG = {"type":"function","function":{"name":"add_egg_pancake","description":"加入蛋餅","parameters":{"type":"object","properties":{"flavor":{"type":"string"},"quantity":{"type":"integer"},"customization":{"type":"string"}},"required":["flavor"]}}}
T_SNACK = {"type":"function","function":{"name":"add_snack","description":"加入點心","parameters":{"type":"object","properties":{"flavor":{"type":"string"},"quantity":{"type":"integer"},"customization":{"type":"string"}},"required":["flavor"]}}}
T_COMBO = {"type":"function","function":{"name":"add_combo","description":"加入套餐","parameters":{"type":"object","properties":{"combo_name":{"type":"string"},"rice":{"type":"string","enum":["白米","紫米","混米"]},"temp":{"type":"string","enum":["冰","溫","熱"]},"flavor":{"type":"string"},"quantity":{"type":"integer"},"customization":{"type":"string"}},"required":["combo_name"]}}}
T_FINAL = {"type":"function","function":{"name":"finalize_order","description":"結帳","parameters":{"type":"object","properties":{"dine_type":{"type":"string"},"payment_method":{"type":"string"}},"required":["dine_type","payment_method"]}}}

def sys_msg():
    return {"role":"system","content":SYSTEM}
def user(text):
    return {"role":"user","content":text}
def asst(text):
    return {"role":"assistant","content":text}
def asst_call(call_id, name, args):
    return {"role":"assistant","content":None,"tool_calls":[{"id":call_id,"type":"function","function":{"name":name,"arguments":args}}]}
def tool_resp(call_id, ok, item_id, msg, cart_count, **extra):
    d = {"ok":ok,"item_id":item_id,"message":msg,"cart_count":cart_count}
    d.update(extra)
    return {"role":"tool","content":json.dumps(d,ensure_ascii=False),"tool_call_id":call_id}
def final_resp(call_id, order_num, total, item_count, dine, pay):
    d = {"ok":True,"order_number":order_num,"total":total,"item_count":item_count,"dine_type":dine,"payment_method":pay}
    return {"role":"tool","content":json.dumps(d,ensure_ascii=False),"tool_call_id":call_id}
def entry(messages, tools):
    return json.dumps({"messages":messages,"tools":tools},ensure_ascii=False)

rows = []
order_num = 301

# ============ 2品項 (10筆) ============

# 1: 套餐+飲料
msgs = [sys_msg(), user("套餐一 再加一杯大杯冰紅茶"),
    asst_call("call_1","add_combo",{"combo_name":"套餐一","temp":"冰"}),
    tool_resp("call_1",True,"combo_1","已加入 套餐一 醬燒肉片蛋餅+豆漿(大)",1),
    asst_call("call_2","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_2",True,"drink_1","已加入 1份 大杯冰精選紅茶",2),
    asst("好，套餐一跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_3",order_num,105,2,"take-out","cash"),
    asst(f"好，總共 105 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_DRINK,T_FINAL])); order_num+=1

# 2: 套餐+飲料
msgs = [sys_msg(), user("套餐三 熱的 還要一杯中溫豆漿"),
    asst_call("call_1","add_combo",{"combo_name":"套餐三","temp":"熱"}),
    tool_resp("call_1",True,"combo_1","已加入 套餐三 高麗菜蛋餅+純鮮奶茶(大)",1),
    asst_call("call_2","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"溫"}),
    tool_resp("call_2",True,"drink_1","已加入 1份 中杯溫有糖豆漿",2),
    asst("好，套餐三跟中杯溫豆漿～還需要什麼嗎？"),
    user("就這樣 內用 Line Pay"),
    asst_call("call_3","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_3",order_num,100,2,"dine-in","line_pay"),
    asst(f"好，總共 100 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_DRINK,T_FINAL])); order_num+=1

# 3: 飯糰+套餐
msgs = [sys_msg(), user("咖哩嫩雞紫米飯糰 跟套餐二"),
    asst_call("call_1","add_riceball",{"flavor":"咖哩嫩雞","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米咖哩嫩雞飯糰",1),
    asst_call("call_2","add_combo",{"combo_name":"套餐二"}),
    tool_resp("call_2",True,"combo_1","已加入 套餐二 源味飯糰+十穀漿(中)",2),
    asst("好，咖哩嫩雞紫米飯糰跟套餐二～還需要什麼嗎？"),
    user("不用 外帶 付現"),
    asst_call("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_3",order_num,140,2,"take-out","cash"),
    asst(f"好，總共 140 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_COMBO,T_FINAL])); order_num+=1

# 4: 飯糰+套餐
msgs = [sys_msg(), user("蜜汁燒肉白米飯糰 加套餐五 溫的"),
    asst_call("call_1","add_riceball",{"flavor":"蜜汁燒肉","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米蜜汁燒肉飯糰",1),
    asst_call("call_2","add_combo",{"combo_name":"套餐五","temp":"溫"}),
    tool_resp("call_2",True,"combo_1","已加入 套餐五 起司蛋饅頭+燕麥薏仁漿(大)",2),
    asst("好，蜜汁燒肉白米飯糰跟套餐五～還需要什麼嗎？"),
    user("沒了 內用 現金"),
    asst_call("call_3","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_3",order_num,145,2,"dine-in","cash"),
    asst(f"好，總共 145 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_COMBO,T_FINAL])); order_num+=1

# 5: 蛋餅x2
msgs = [sys_msg(), user("一個起司蛋餅 一個鮪魚蛋餅"),
    asst_call("call_1","add_egg_pancake",{"flavor":"起司"}),
    tool_resp("call_1",True,"egg_pancake_1","已加入 1份 起司蛋餅",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"鮪魚"}),
    tool_resp("call_2",True,"egg_pancake_2","已加入 1份 鮪魚蛋餅",2),
    asst("好，起司蛋餅跟鮪魚蛋餅～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_3",order_num,95,2,"take-out","cash"),
    asst(f"好，總共 95 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_EGG,T_FINAL])); order_num+=1

# 6: 蛋餅x2
msgs = [sys_msg(), user("培根蛋餅跟醬燒肉片蛋餅"),
    asst_call("call_1","add_egg_pancake",{"flavor":"培根"}),
    tool_resp("call_1",True,"egg_pancake_1","已加入 1份 培根蛋餅",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"醬燒肉片"}),
    tool_resp("call_2",True,"egg_pancake_2","已加入 1份 醬燒肉片蛋餅",2),
    asst("好，培根蛋餅跟醬燒肉片蛋餅～還需要什麼嗎？"),
    user("就這樣 內用 Line Pay"),
    asst_call("call_3","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_3",order_num,105,2,"dine-in","line_pay"),
    asst(f"好，總共 105 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_EGG,T_FINAL])); order_num+=1

# 7: 果醬+飲料
msgs = [sys_msg(), user("花生厚片吐司 大杯冰豆漿"),
    asst_call("call_1","add_snack",{"flavor":"果醬吐司(花生/厚片)"}),
    tool_resp("call_1",True,"snack_1","已加入 1份 果醬吐司(花生/厚片)",1),
    asst_call("call_2","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_2",True,"drink_1","已加入 1份 大杯冰有糖豆漿",2),
    asst("好，花生厚片吐司跟大杯冰豆漿～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_3",order_num,55,2,"take-out","cash"),
    asst(f"好，總共 55 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 8: 果醬+飲料
msgs = [sys_msg(), user("草莓薄片吐司 中杯溫鮮奶茶"),
    asst_call("call_1","add_snack",{"flavor":"果醬吐司(草莓/薄片)"}),
    tool_resp("call_1",True,"snack_1","已加入 1份 果醬吐司(草莓/薄片)",1),
    asst_call("call_2","add_drink",{"flavor":"純鮮奶茶","size":"中杯","temp":"溫"}),
    tool_resp("call_2",True,"drink_1","已加入 1份 中杯溫純鮮奶茶",2),
    asst("好，草莓薄片吐司跟中杯溫鮮奶茶～還需要什麼嗎？"),
    user("不用 內用 現金"),
    asst_call("call_3","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_3",order_num,55,2,"dine-in","cash"),
    asst(f"好，總共 55 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 9: 點心x2
msgs = [sys_msg(), user("煎餃跟港式蘿蔔糕各一份"),
    asst_call("call_1","add_snack",{"flavor":"煎餃(8顆)"}),
    tool_resp("call_1",True,"snack_1","已加入 1份 煎餃(8顆)",1),
    asst_call("call_2","add_snack",{"flavor":"港式蘿蔔糕"}),
    tool_resp("call_2",True,"snack_2","已加入 1份 港式蘿蔔糕",2),
    asst("好，煎餃跟港式蘿蔔糕～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_3","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_3",order_num,80,2,"take-out","cash"),
    asst(f"好，總共 80 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_SNACK,T_FINAL])); order_num+=1

# 10: 點心x2
msgs = [sys_msg(), user("雞塊跟脆薯"),
    asst_call("call_1","add_snack",{"flavor":"麥克雞塊(5個)"}),
    tool_resp("call_1",True,"snack_1","已加入 1份 麥克雞塊(5個)",1),
    asst_call("call_2","add_snack",{"flavor":"香酥脆薯"}),
    tool_resp("call_2",True,"snack_2","已加入 1份 香酥脆薯",2),
    asst("好，雞塊跟脆薯～還需要什麼嗎？"),
    user("就這樣 內用 Line Pay"),
    asst_call("call_3","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_3",order_num,80,2,"dine-in","line_pay"),
    asst(f"好，總共 80 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_SNACK,T_FINAL])); order_num+=1

# ============ 3品項 (15筆) ============

# 11: 飯糰+吐司+飲料
msgs = [sys_msg(), user("沙茶豬肉混米飯糰 火腿蛋吐司 大杯冰紅茶"),
    asst_call("call_1","add_riceball",{"flavor":"沙茶豬肉","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米沙茶豬肉飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"吐司","flavor":"火腿蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 火腿蛋吐司",2),
    asst_call("call_3","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰精選紅茶",3),
    asst("好，沙茶豬肉混米飯糰、火腿蛋吐司跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,135,3,"take-out","cash"),
    asst(f"好，總共 135 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 12: 飯糰+吐司+飲料
msgs = [sys_msg(), user("香濃起司白米飯糰 培根蛋吐司 中杯溫豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"香濃起司","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米香濃起司飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"吐司","flavor":"培根蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 培根蛋吐司",2),
    asst_call("call_3","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"溫"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 中杯溫有糖豆漿",3),
    asst("好，香濃起司白米飯糰、培根蛋吐司跟中杯溫豆漿～還需要什麼嗎？"),
    user("就這樣 內用 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_4",order_num,130,3,"dine-in","cash"),
    asst(f"好，總共 130 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 13: 飯糰+吐司+飲料
msgs = [sys_msg(), user("蒜香雞肉紫米飯糰 起司蛋吐司 大杯熱鮮奶茶"),
    asst_call("call_1","add_riceball",{"flavor":"蒜香雞肉","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米蒜香雞肉飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"吐司","flavor":"起司蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 起司蛋吐司",2),
    asst_call("call_3","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"熱"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯熱純鮮奶茶",3),
    asst("好，蒜香雞肉紫米飯糰、起司蛋吐司跟大杯熱鮮奶茶～還需要什麼嗎？"),
    user("不用了 外帶 Line Pay"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_4",order_num,150,3,"take-out","line_pay"),
    asst(f"好，總共 150 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 14: 蛋餅+漢堡+飲料
msgs = [sys_msg(), user("玉米蛋餅 火腿蛋漢堡 大杯冰豆漿"),
    asst_call("call_1","add_egg_pancake",{"flavor":"玉米"}),
    tool_resp("call_1",True,"egg_pancake_1","已加入 1份 玉米蛋餅",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"火腿蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 火腿蛋漢堡",2),
    asst_call("call_3","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰有糖豆漿",3),
    asst("好，玉米蛋餅、火腿蛋漢堡跟大杯冰豆漿～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,115,3,"take-out","cash"),
    asst(f"好，總共 115 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_EGG,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 15: 蛋餅+漢堡+飲料
msgs = [sys_msg(), user("高麗菜蛋餅 起司蛋漢堡 中杯熱紅茶"),
    asst_call("call_1","add_egg_pancake",{"flavor":"高麗菜"}),
    tool_resp("call_1",True,"egg_pancake_1","已加入 1份 高麗菜蛋餅",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"起司蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 起司蛋漢堡",2),
    asst_call("call_3","add_drink",{"flavor":"精選紅茶","size":"中杯","temp":"熱"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 中杯熱精選紅茶",3),
    asst("好，高麗菜蛋餅、起司蛋漢堡跟中杯熱紅茶～還需要什麼嗎？"),
    user("就這樣 內用 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_4",order_num,115,3,"dine-in","cash"),
    asst(f"好，總共 115 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_EGG,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 16: 蛋餅+漢堡+飲料
msgs = [sys_msg(), user("醬燒肉片蛋餅 豬肉蛋漢堡 大杯溫米漿"),
    asst_call("call_1","add_egg_pancake",{"flavor":"醬燒肉片"}),
    tool_resp("call_1",True,"egg_pancake_1","已加入 1份 醬燒肉片蛋餅",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"豬肉蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 豬肉蛋漢堡",2),
    asst_call("call_3","add_drink",{"flavor":"花生糙米漿","size":"大杯","temp":"溫"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯溫花生糙米漿",3),
    asst("好，醬燒肉片蛋餅、豬肉蛋漢堡跟大杯溫米漿～還需要什麼嗎？"),
    user("不用 外帶 Line Pay"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_4",order_num,140,3,"take-out","line_pay"),
    asst(f"好，總共 140 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_EGG,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 17: 飯糰+蛋餅+飲料
msgs = [sys_msg(), user("和風雞肉白米飯糰 原味蛋餅 中杯冰綠茶"),
    asst_call("call_1","add_riceball",{"flavor":"和風雞肉","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米和風雞肉飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"原味"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 原味蛋餅",2),
    asst_call("call_3","add_drink",{"flavor":"無糖清香綠茶","size":"中杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 中杯冰無糖清香綠茶",3),
    asst("好，和風雞肉白米飯糰、原味蛋餅跟中杯冰綠茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,120,3,"take-out","cash"),
    asst(f"好，總共 120 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 18: 飯糰+蛋餅+飲料
msgs = [sys_msg(), user("椒鹽雞絲紫米飯糰 肉鬆蛋餅 大杯熱豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"椒鹽雞絲","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米椒鹽雞絲飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"肉鬆"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 肉鬆蛋餅",2),
    asst_call("call_3","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"熱"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯熱有糖豆漿",3),
    asst("好，椒鹽雞絲紫米飯糰、肉鬆蛋餅跟大杯熱豆漿～還需要什麼嗎？"),
    user("沒了 內用 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_4",order_num,135,3,"dine-in","cash"),
    asst(f"好，總共 135 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 19: 飯糰+蛋餅+飲料
msgs = [sys_msg(), user("韓式泡菜混米飯糰 薯餅蛋餅 大杯冰紅茶豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"韓式泡菜","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米韓式泡菜飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"薯餅"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 薯餅蛋餅",2),
    asst_call("call_3","add_drink",{"flavor":"紅茶+豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰紅茶+豆漿",3),
    asst("好，韓式泡菜混米飯糰、薯餅蛋餅跟大杯冰紅茶豆漿～還需要什麼嗎？"),
    user("就這樣 外帶 Line Pay"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_4",order_num,135,3,"take-out","line_pay"),
    asst(f"好，總共 135 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 20: 饅頭+點心+飲料
msgs = [sys_msg(), user("鮮肉包兩個 煎餃 大杯冰紅茶"),
    asst_call("call_1","add_carrier",{"carrier":"饅頭","flavor":"鮮肉包","quantity":2}),
    tool_resp("call_1",True,"carrier_1","已加入 2份 鮮肉包",1),
    asst_call("call_2","add_snack",{"flavor":"煎餃(8顆)"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 煎餃(8顆)",2),
    asst_call("call_3","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰精選紅茶",3),
    asst("好，兩個鮮肉包、煎餃跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,95,3,"take-out","cash"),
    asst(f"好，總共 95 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 21: 饅頭+點心+飲料
msgs = [sys_msg(), user("黑糖饅頭 薯餅 中杯溫米漿"),
    asst_call("call_1","add_carrier",{"carrier":"饅頭","flavor":"黑糖饅頭"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 黑糖饅頭",1),
    asst_call("call_2","add_snack",{"flavor":"薯餅(1片)"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 薯餅(1片)",2),
    asst_call("call_3","add_drink",{"flavor":"花生糙米漿","size":"中杯","temp":"溫"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 中杯溫花生糙米漿",3),
    asst("好，黑糖饅頭、薯餅跟中杯溫米漿～還需要什麼嗎？"),
    user("不用 內用 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_4",order_num,60,3,"dine-in","cash"),
    asst(f"好，總共 60 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 22: 饅頭+點心+飲料
msgs = [sys_msg(), user("芋頭饅頭 荷包蛋 大杯熱十穀漿"),
    asst_call("call_1","add_carrier",{"carrier":"饅頭","flavor":"芋頭饅頭"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 芋頭饅頭",1),
    asst_call("call_2","add_snack",{"flavor":"荷包蛋"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 荷包蛋",2),
    asst_call("call_3","add_drink",{"flavor":"十穀漿","size":"大杯","temp":"熱"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯熱十穀漿",3),
    asst("好，芋頭饅頭、荷包蛋跟大杯熱十穀漿～還需要什麼嗎？"),
    user("就這樣 外帶 Line Pay"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_4",order_num,65,3,"take-out","line_pay"),
    asst(f"好，總共 65 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 23: 套餐+點心+飲料
msgs = [sys_msg(), user("套餐四 冰的 港式蘿蔔糕 大杯冰綠茶"),
    asst_call("call_1","add_combo",{"combo_name":"套餐四","temp":"冰"}),
    tool_resp("call_1",True,"combo_1","已加入 套餐四 蘿蔔糕二片+蛋+花生糙米漿(中)",1),
    asst_call("call_2","add_snack",{"flavor":"港式蘿蔔糕"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 港式蘿蔔糕",2),
    asst_call("call_3","add_drink",{"flavor":"無糖清香綠茶","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰無糖清香綠茶",3),
    asst("好，套餐四、港式蘿蔔糕跟大杯冰綠茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,140,3,"take-out","cash"),
    asst(f"好，總共 140 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 24: 套餐+點心+飲料
msgs = [sys_msg(), user("套餐六 溫的 熱狗 中杯冰豆漿"),
    asst_call("call_1","add_combo",{"combo_name":"套餐六","temp":"溫"}),
    tool_resp("call_1",True,"combo_1","已加入 套餐六 鐵板麵+肉片+蛋+紅茶(大)",1),
    asst_call("call_2","add_snack",{"flavor":"熱狗(3條)"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 熱狗(3條)",2),
    asst_call("call_3","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 中杯冰有糖豆漿",3),
    asst("好，套餐六、熱狗跟中杯冰豆漿～還需要什麼嗎？"),
    user("不用了 內用 Line Pay"),
    asst_call("call_4","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_4",order_num,150,3,"dine-in","line_pay"),
    asst(f"好，總共 150 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 25: 套餐+點心+飲料
msgs = [sys_msg(), user("兒童餐 冰的 加一份雞塊 大杯冰紅茶"),
    asst_call("call_1","add_combo",{"combo_name":"兒童餐","temp":"冰"}),
    tool_resp("call_1",True,"combo_1","已加入 兒童餐 薯條+雞塊*4+果醬吐司+紅茶(中)",1),
    asst_call("call_2","add_snack",{"flavor":"麥克雞塊(5個)"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 麥克雞塊(5個)",2),
    asst_call("call_3","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰精選紅茶",3),
    asst("好，兒童餐、雞塊跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,150,3,"take-out","cash"),
    asst(f"好，總共 150 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# ============ 4品項 (15筆) ============

# 26: 家庭4人
msgs = [sys_msg(), user("醬燒里肌紫米飯糰 起司蛋餅 培根蛋漢堡 大杯冰紅茶"),
    asst_call("call_1","add_riceball",{"flavor":"醬燒里肌","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米醬燒里肌飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"起司"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 起司蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"漢堡","flavor":"培根蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 培根蛋漢堡",3),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰精選紅茶",4),
    asst("好，醬燒里肌紫米飯糰、起司蛋餅、培根蛋漢堡跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,185,4,"take-out","cash"),
    asst(f"好，總共 185 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 27: 家庭4人
msgs = [sys_msg(), user("嫩汁雞排白米飯糰 鮪魚蛋吐司 火腿蛋餅 大杯溫豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"嫩汁雞排","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米嫩汁雞排飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"吐司","flavor":"鮪魚蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 鮪魚蛋吐司",2),
    asst_call("call_3","add_egg_pancake",{"flavor":"火腿"}),
    tool_resp("call_3",True,"egg_pancake_1","已加入 1份 火腿蛋餅",3),
    asst_call("call_4","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"溫"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯溫有糖豆漿",4),
    asst("好，嫩汁雞排白米飯糰、鮪魚蛋吐司、火腿蛋餅跟大杯溫豆漿～還需要什麼嗎？"),
    user("就這樣 內用 Line Pay"),
    asst_call("call_5","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_5",order_num,195,4,"dine-in","line_pay"),
    asst(f"好，總共 195 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 28: 家庭4人
msgs = [sys_msg(), user("黑椒里肌混米飯糰 醬燒肉片蛋漢堡 煎餃 大杯冰鮮奶茶"),
    asst_call("call_1","add_riceball",{"flavor":"黑椒里肌","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米黑椒里肌飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"醬燒肉片蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 醬燒肉片蛋漢堡",2),
    asst_call("call_3","add_snack",{"flavor":"煎餃(8顆)"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 煎餃(8顆)",3),
    asst_call("call_4","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰純鮮奶茶",4),
    asst("好，黑椒里肌混米飯糰、醬燒肉片蛋漢堡、煎餃跟大杯冰鮮奶茶～還需要什麼嗎？"),
    user("不用了 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,235,4,"take-out","cash"),
    asst(f"好，總共 235 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 29: 家庭4人
msgs = [sys_msg(), user("豬肉蛋吐司 洋蔥蛋餅 肉鬆蛋饅頭 大杯冰紅茶"),
    asst_call("call_1","add_carrier",{"carrier":"吐司","flavor":"豬肉蛋"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 豬肉蛋吐司",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"洋蔥"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 洋蔥蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"饅頭","flavor":"肉鬆蛋"}),
    tool_resp("call_3",True,"carrier_2","已加入 1份 肉鬆蛋饅頭",3),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰精選紅茶",4),
    asst("好，豬肉蛋吐司、洋蔥蛋餅、肉鬆蛋饅頭跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,155,4,"take-out","cash"),
    asst(f"好，總共 155 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 30: 家庭4人
msgs = [sys_msg(), user("套餐五 熱的 風味火腿紫米飯糰 紫米蛋餅 大杯冰豆漿"),
    asst_call("call_1","add_combo",{"combo_name":"套餐五","temp":"熱"}),
    tool_resp("call_1",True,"combo_1","已加入 套餐五 起司蛋饅頭+燕麥薏仁漿(大)",1),
    asst_call("call_2","add_riceball",{"flavor":"風味火腿","rice":"紫米"}),
    tool_resp("call_2",True,"riceball_1","已加入 1份 紫米風味火腿飯糰",2),
    asst_call("call_3","add_egg_pancake",{"flavor":"紫米"}),
    tool_resp("call_3",True,"egg_pancake_1","已加入 1份 紫米蛋餅",3),
    asst_call("call_4","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰有糖豆漿",4),
    asst("好，套餐五、風味火腿紫米飯糰、紫米蛋餅跟大杯冰豆漿～還需要什麼嗎？"),
    user("就這樣 內用 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_5",order_num,205,4,"dine-in","cash"),
    asst(f"好，總共 205 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 31: 飯糰x2+蛋餅+飲料
msgs = [sys_msg(), user("源味傳統白米飯糰 鮪魚混米飯糰 玉米蛋餅 大杯冰紅茶"),
    asst_call("call_1","add_riceball",{"flavor":"源味傳統","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米源味傳統飯糰",1),
    asst_call("call_2","add_riceball",{"flavor":"鮪魚","rice":"混米"}),
    tool_resp("call_2",True,"riceball_2","已加入 1份 混米鮪魚飯糰",2),
    asst_call("call_3","add_egg_pancake",{"flavor":"玉米"}),
    tool_resp("call_3",True,"egg_pancake_1","已加入 1份 玉米蛋餅",3),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰精選紅茶",4),
    asst("好，源味傳統白米飯糰、鮪魚混米飯糰、玉米蛋餅跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 Line Pay"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_5",order_num,175,4,"take-out","line_pay"),
    asst(f"好，總共 175 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 32: 飯糰x2+蛋餅+飲料
msgs = [sys_msg(), user("半甜鹹白米飯糰 蔥蛋豆芽紫米飯糰 培根蛋餅 中杯溫豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"半甜鹹","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米半甜鹹飯糰",1),
    asst_call("call_2","add_riceball",{"flavor":"蔥蛋豆芽","rice":"紫米"}),
    tool_resp("call_2",True,"riceball_2","已加入 1份 紫米蔥蛋豆芽飯糰",2),
    asst_call("call_3","add_egg_pancake",{"flavor":"培根"}),
    tool_resp("call_3",True,"egg_pancake_1","已加入 1份 培根蛋餅",3),
    asst_call("call_4","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"溫"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 中杯溫有糖豆漿",4),
    asst("好，半甜鹹白米飯糰、蔥蛋豆芽紫米飯糰、培根蛋餅跟中杯溫豆漿～還需要什麼嗎？"),
    user("不用 內用 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_5",order_num,175,4,"dine-in","cash"),
    asst(f"好，總共 175 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 33: 飯糰x2+蛋餅+飲料
msgs = [sys_msg(), user("茄汁蛋包混米飯糰 香煎吻魚白米飯糰 油條蛋餅 大杯熱鮮奶咖啡"),
    asst_call("call_1","add_riceball",{"flavor":"茄汁蛋包","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米茄汁蛋包飯糰",1),
    asst_call("call_2","add_riceball",{"flavor":"香煎吻魚","rice":"白米"}),
    tool_resp("call_2",True,"riceball_2","已加入 1份 白米香煎吻魚飯糰",2),
    asst_call("call_3","add_egg_pancake",{"flavor":"油條"}),
    tool_resp("call_3",True,"egg_pancake_1","已加入 1份 油條蛋餅",3),
    asst_call("call_4","add_drink",{"flavor":"純鮮奶咖啡","size":"大杯","temp":"熱"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯熱純鮮奶咖啡",4),
    asst("好，茄汁蛋包混米飯糰、香煎吻魚白米飯糰、油條蛋餅跟大杯熱鮮奶咖啡～還需要什麼嗎？"),
    user("就這樣 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,225,4,"take-out","cash"),
    asst(f"好，總共 225 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 34: 吐司+漢堡+點心+飲料
msgs = [sys_msg(), user("蜜汁燒肉蛋吐司 薯餅蛋漢堡 香酥脆薯 大杯冰紅茶豆漿"),
    asst_call("call_1","add_carrier",{"carrier":"吐司","flavor":"蜜汁燒肉蛋"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 蜜汁燒肉蛋吐司",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"薯餅蛋"}),
    tool_resp("call_2",True,"carrier_2","已加入 1份 薯餅蛋漢堡",2),
    asst_call("call_3","add_snack",{"flavor":"香酥脆薯"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 香酥脆薯",3),
    asst_call("call_4","add_drink",{"flavor":"紅茶+豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰紅茶+豆漿",4),
    asst("好，蜜汁燒肉蛋吐司、薯餅蛋漢堡、香酥脆薯跟大杯冰紅茶豆漿～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,175,4,"take-out","cash"),
    asst(f"好，總共 175 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 35: 吐司+漢堡+點心+飲料
msgs = [sys_msg(), user("黑椒肉片蛋吐司 鮪魚蛋漢堡 韭菜餡餅 大杯冰豆漿"),
    asst_call("call_1","add_carrier",{"carrier":"吐司","flavor":"黑椒肉片蛋"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 黑椒肉片蛋吐司",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"鮪魚蛋"}),
    tool_resp("call_2",True,"carrier_2","已加入 1份 鮪魚蛋漢堡",2),
    asst_call("call_3","add_snack",{"flavor":"韭菜餡餅(5顆)"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 韭菜餡餅(5顆)",3),
    asst_call("call_4","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰有糖豆漿",4),
    asst("好，黑椒肉片蛋吐司、鮪魚蛋漢堡、韭菜餡餅跟大杯冰豆漿～還需要什麼嗎？"),
    user("就這樣 內用 Line Pay"),
    asst_call("call_5","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_5",order_num,185,4,"dine-in","line_pay"),
    asst(f"好，總共 185 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 36: 吐司+漢堡+點心+飲料
msgs = [sys_msg(), user("原味咔啦雞蛋吐司 椒鹽雞絲蛋漢堡 蘿蔔糕 大杯熱紅茶"),
    asst_call("call_1","add_carrier",{"carrier":"吐司","flavor":"原味咔啦雞蛋"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 原味咔啦雞蛋吐司",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"椒鹽雞絲蛋"}),
    tool_resp("call_2",True,"carrier_2","已加入 1份 椒鹽雞絲蛋漢堡",2),
    asst_call("call_3","add_snack",{"flavor":"港式蘿蔔糕"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 港式蘿蔔糕",3),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"熱"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯熱精選紅茶",4),
    asst("好，原味咔啦雞蛋吐司、椒鹽雞絲蛋漢堡、蘿蔔糕跟大杯熱紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,225,4,"take-out","cash"),
    asst(f"好，總共 225 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 37: 含追問 - 飯糰缺米種+蛋餅缺口味+飲料缺規格
msgs = [sys_msg(), user("蒜香雞肉飯糰 蛋餅 紅茶 還有薯餅"),
    asst("好，蒜香雞肉飯糰要白米紫米還是混米？"),
    user("紫米"),
    asst_call("call_1","add_riceball",{"flavor":"蒜香雞肉","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米蒜香雞肉飯糰",1),
    asst("好，紫米蒜香雞肉飯糰～蛋餅要什麼口味？"),
    user("起司"),
    asst_call("call_2","add_egg_pancake",{"flavor":"起司"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 起司蛋餅",2),
    asst_call("call_3","add_snack",{"flavor":"薯餅(1片)"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 薯餅(1片)",3),
    asst("好，起司蛋餅跟薯餅～紅茶要中杯大杯？冰的溫的熱的？"),
    user("大杯冰的"),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰精選紅茶",4),
    asst("好，大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,155,4,"take-out","cash"),
    asst(f"好，總共 155 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 38: 含追問 - 飯糰缺米種
msgs = [sys_msg(), user("咖哩嫩雞飯糰 起司蛋漢堡 大杯冰綠茶 再一個荷包蛋"),
    asst("好，咖哩嫩雞飯糰要白米紫米還是混米？"),
    user("白米"),
    asst_call("call_1","add_riceball",{"flavor":"咖哩嫩雞","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米咖哩嫩雞飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"漢堡","flavor":"起司蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 起司蛋漢堡",2),
    asst_call("call_3","add_snack",{"flavor":"荷包蛋"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 荷包蛋",3),
    asst_call("call_4","add_drink",{"flavor":"無糖清香綠茶","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰無糖清香綠茶",4),
    asst("好，咖哩嫩雞白米飯糰、起司蛋漢堡、荷包蛋跟大杯冰綠茶～還需要什麼嗎？"),
    user("不用 內用 Line Pay"),
    asst_call("call_5","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_5",order_num,155,4,"dine-in","line_pay"),
    asst(f"好，總共 155 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 39: 含追問 - 飲料缺規格
msgs = [sys_msg(), user("火腿蛋吐司 培根蛋餅 蘿蔔糕 豆漿"),
    asst_call("call_1","add_carrier",{"carrier":"吐司","flavor":"火腿蛋"}),
    tool_resp("call_1",True,"carrier_1","已加入 1份 火腿蛋吐司",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"培根"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 培根蛋餅",2),
    asst_call("call_3","add_snack",{"flavor":"港式蘿蔔糕"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 港式蘿蔔糕",3),
    asst("好，火腿蛋吐司、培根蛋餅跟蘿蔔糕～豆漿要中杯大杯？冰的溫的熱的？"),
    user("中杯熱的"),
    asst_call("call_4","add_drink",{"flavor":"有糖豆漿","size":"中杯","temp":"熱"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 中杯熱有糖豆漿",4),
    asst("好，中杯熱豆漿～還需要什麼嗎？"),
    user("沒了 外帶 付現"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,150,4,"take-out","cash"),
    asst(f"好，總共 150 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_EGG,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 40: 含追問 - 蛋餅缺口味+飯糰缺細節
msgs = [sys_msg(), user("飯糰兩個 蛋餅 大杯冰米漿"),
    asst("好，兩個飯糰要什麼口味跟米種？"),
    user("一個咖哩嫩雞紫米 一個沙茶豬肉白米"),
    asst_call("call_1","add_riceball",{"flavor":"咖哩嫩雞","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米咖哩嫩雞飯糰",1),
    asst_call("call_2","add_riceball",{"flavor":"沙茶豬肉","rice":"白米"}),
    tool_resp("call_2",True,"riceball_2","已加入 1份 白米沙茶豬肉飯糰",2),
    asst("好～蛋餅要什麼口味？"),
    user("高麗菜"),
    asst_call("call_3","add_egg_pancake",{"flavor":"高麗菜"}),
    tool_resp("call_3",True,"egg_pancake_1","已加入 1份 高麗菜蛋餅",3),
    asst_call("call_4","add_drink",{"flavor":"花生糙米漿","size":"大杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯冰花生糙米漿",4),
    asst("好，高麗菜蛋餅跟大杯冰米漿～還需要什麼嗎？"),
    user("就這樣 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,215,4,"take-out","cash"),
    asst(f"好，總共 215 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# ============ 5品項 (10筆) ============

# 41: 5個不同品項
msgs = [sys_msg(), user("懷古鹹蛋白米飯糰 火腿蛋餅 薯餅蛋吐司 煎餃 大杯冰紅茶"),
    asst_call("call_1","add_riceball",{"flavor":"懷古鹹蛋","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米懷古鹹蛋飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"火腿"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 火腿蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"吐司","flavor":"薯餅蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 薯餅蛋吐司",3),
    asst_call("call_4","add_snack",{"flavor":"煎餃(8顆)"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 煎餃(8顆)",4),
    asst_call("call_5","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯冰精選紅茶",5),
    asst("好，懷古鹹蛋白米飯糰、火腿蛋餅、薯餅蛋吐司、煎餃跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_6",order_num,220,5,"take-out","cash"),
    asst(f"好，總共 220 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 42: 5個不同品項
msgs = [sys_msg(), user("甜心芋泥紫米飯糰 洋蔥蛋餅 豬肉蛋漢堡 雞塊 大杯冰豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"甜心芋泥","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米甜心芋泥飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"洋蔥"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 洋蔥蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"漢堡","flavor":"豬肉蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 豬肉蛋漢堡",3),
    asst_call("call_4","add_snack",{"flavor":"麥克雞塊(5個)"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 麥克雞塊(5個)",4),
    asst_call("call_5","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯冰有糖豆漿",5),
    asst("好，甜心芋泥紫米飯糰、洋蔥蛋餅、豬肉蛋漢堡、雞塊跟大杯冰豆漿～還需要什麼嗎？"),
    user("不用了 內用 Line Pay"),
    asst_call("call_6","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_6",order_num,220,5,"dine-in","line_pay"),
    asst(f"好，總共 220 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 43: 5個不同品項
msgs = [sys_msg(), user("QQ滷蛋混米飯糰 韓式泡菜蛋餅 培根蛋吐司 蔥蛋 大杯溫十穀漿"),
    asst_call("call_1","add_riceball",{"flavor":"QQ滷蛋","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米QQ滷蛋飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"韓式泡菜"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 韓式泡菜蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"吐司","flavor":"培根蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 培根蛋吐司",3),
    asst_call("call_4","add_snack",{"flavor":"蔥蛋"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 蔥蛋",4),
    asst_call("call_5","add_drink",{"flavor":"十穀漿","size":"大杯","temp":"溫"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯溫十穀漿",5),
    asst("好，QQ滷蛋混米飯糰、韓式泡菜蛋餅、培根蛋吐司、蔥蛋跟大杯溫十穀漿～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_6",order_num,210,5,"take-out","cash"),
    asst(f"好，總共 210 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 44: 5個不同品項
msgs = [sys_msg(), user("香燻培根紫米飯糰 甜芋起司蛋餅 火腿蛋漢堡 港式蘿蔔糕 大杯冰鮮奶茶"),
    asst_call("call_1","add_riceball",{"flavor":"香燻培根","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米香燻培根飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"甜芋起司"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 甜芋起司蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"漢堡","flavor":"火腿蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 火腿蛋漢堡",3),
    asst_call("call_4","add_snack",{"flavor":"港式蘿蔔糕"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 港式蘿蔔糕",4),
    asst_call("call_5","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯冰純鮮奶茶",5),
    asst("好，香燻培根紫米飯糰、甜芋起司蛋餅、火腿蛋漢堡、蘿蔔糕跟大杯冰鮮奶茶～還需要什麼嗎？"),
    user("就這樣 外帶 Line Pay"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_6",order_num,250,5,"take-out","line_pay"),
    asst(f"好，總共 250 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 45: quantity>1
msgs = [sys_msg(), user("和風雞肉白米飯糰兩個 起司蛋餅 大杯冰紅茶兩杯 一個荷包蛋"),
    asst_call("call_1","add_riceball",{"flavor":"和風雞肉","rice":"白米","quantity":2}),
    tool_resp("call_1",True,"riceball_1","已加入 2份 白米和風雞肉飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"起司"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 起司蛋餅",2),
    asst_call("call_3","add_snack",{"flavor":"荷包蛋"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 荷包蛋",3),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰","quantity":2}),
    tool_resp("call_4",True,"drink_1","已加入 2份 大杯冰精選紅茶",4),
    asst("好，兩個和風雞肉白米飯糰、起司蛋餅、荷包蛋跟兩杯大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,245,5,"take-out","cash"),
    asst(f"好，總共 245 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 46: quantity>1
msgs = [sys_msg(), user("鮮肉包三個 醬燒肉片蛋餅 香濃起司混米飯糰 大杯熱豆漿 薯餅"),
    asst_call("call_1","add_carrier",{"carrier":"饅頭","flavor":"鮮肉包","quantity":3}),
    tool_resp("call_1",True,"carrier_1","已加入 3份 鮮肉包",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"醬燒肉片"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 醬燒肉片蛋餅",2),
    asst_call("call_3","add_riceball",{"flavor":"香濃起司","rice":"混米"}),
    tool_resp("call_3",True,"riceball_1","已加入 1份 混米香濃起司飯糰",3),
    asst_call("call_4","add_snack",{"flavor":"薯餅(1片)"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 薯餅(1片)",4),
    asst_call("call_5","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"熱"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯熱有糖豆漿",5),
    asst("好，三個鮮肉包、醬燒肉片蛋餅、香濃起司混米飯糰、薯餅跟大杯熱豆漿～還需要什麼嗎？"),
    user("不用了 外帶 付現"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_6",order_num,190,5,"take-out","cash"),
    asst(f"好，總共 190 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_CARRIER,T_EGG,T_RICEBALL,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 47: quantity>1
msgs = [sys_msg(), user("玉米蛋餅跟肉鬆蛋餅各一 起司蛋吐司 中杯冰紅茶跟大杯冰豆漿"),
    asst_call("call_1","add_egg_pancake",{"flavor":"玉米"}),
    tool_resp("call_1",True,"egg_pancake_1","已加入 1份 玉米蛋餅",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"肉鬆"}),
    tool_resp("call_2",True,"egg_pancake_2","已加入 1份 肉鬆蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"吐司","flavor":"起司蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 起司蛋吐司",3),
    asst_call("call_4","add_drink",{"flavor":"精選紅茶","size":"中杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 中杯冰精選紅茶",4),
    asst_call("call_5","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_2","已加入 1份 大杯冰有糖豆漿",5),
    asst("好，玉米蛋餅、肉鬆蛋餅、起司蛋吐司、中杯冰紅茶跟大杯冰豆漿～還需要什麼嗎？"),
    user("就這樣 內用 現金"),
    asst_call("call_6","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_6",order_num,165,5,"dine-in","cash"),
    asst(f"好，總共 165 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_EGG,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 48: 含追問5品
msgs = [sys_msg(), user("蜜汁燒肉飯糰 高麗菜蛋餅 培根蛋漢堡 雞塊 米漿"),
    asst("好，蜜汁燒肉飯糰要白米紫米還是混米？"),
    user("混米"),
    asst_call("call_1","add_riceball",{"flavor":"蜜汁燒肉","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米蜜汁燒肉飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"高麗菜"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 高麗菜蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"漢堡","flavor":"培根蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 培根蛋漢堡",3),
    asst_call("call_4","add_snack",{"flavor":"麥克雞塊(5個)"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 麥克雞塊(5個)",4),
    asst("好，蜜汁燒肉混米飯糰、高麗菜蛋餅、培根蛋漢堡跟雞塊～米漿要中杯大杯？冰的溫的？"),
    user("大杯溫的"),
    asst_call("call_5","add_drink",{"flavor":"花生糙米漿","size":"大杯","temp":"溫"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯溫花生糙米漿",5),
    asst("好，大杯溫米漿～還需要什麼嗎？"),
    user("沒了 外帶 Line Pay"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"Line Pay"}),
    final_resp("call_6",order_num,245,5,"take-out","line_pay"),
    asst(f"好，總共 245 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 49: 含追問5品
msgs = [sys_msg(), user("黑椒里肌紫米飯糰 蛋餅 火腿蛋吐司 蘿蔔糕 大杯冰紅茶"),
    asst_call("call_1","add_riceball",{"flavor":"黑椒里肌","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米黑椒里肌飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"吐司","flavor":"火腿蛋"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 火腿蛋吐司",2),
    asst_call("call_3","add_snack",{"flavor":"港式蘿蔔糕"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 港式蘿蔔糕",3),
    asst("好，黑椒里肌紫米飯糰、火腿蛋吐司跟蘿蔔糕～蛋餅要什麼口味？"),
    user("薯餅"),
    asst_call("call_4","add_egg_pancake",{"flavor":"薯餅"}),
    tool_resp("call_4",True,"egg_pancake_1","已加入 1份 薯餅蛋餅",4),
    asst_call("call_5","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯冰精選紅茶",5),
    asst("好，薯餅蛋餅跟大杯冰紅茶～還需要什麼嗎？"),
    user("就這樣 內用 現金"),
    asst_call("call_6","finalize_order",{"dine_type":"內用","payment_method":"現金"}),
    final_resp("call_6",order_num,220,5,"dine-in","cash"),
    asst(f"好，總共 220 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 50: 含追問5品
msgs = [sys_msg(), user("椒鹽雞絲飯糰 甜芋肉鬆蛋餅 起司蛋漢堡 熱狗 豆漿"),
    asst("好，椒鹽雞絲飯糰要白米紫米還是混米？"),
    user("白米"),
    asst_call("call_1","add_riceball",{"flavor":"椒鹽雞絲","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米椒鹽雞絲飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"甜芋肉鬆"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 甜芋肉鬆蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"漢堡","flavor":"起司蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 起司蛋漢堡",3),
    asst_call("call_4","add_snack",{"flavor":"熱狗(3條)"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 熱狗(3條)",4),
    asst("好，椒鹽雞絲白米飯糰、甜芋肉鬆蛋餅、起司蛋漢堡跟熱狗～豆漿要中杯大杯？冰的溫的熱的？"),
    user("大杯冰的"),
    asst_call("call_5","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯冰有糖豆漿",5),
    asst("好，大杯冰豆漿～還需要什麼嗎？"),
    user("不用 外帶 付現"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_6",order_num,215,5,"take-out","cash"),
    asst(f"好，總共 215 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# ============ 連續call強化 (5筆) ============

# 51: 3品項全齊連續call
msgs = [sys_msg(), user("咖哩嫩雞紫米飯糰 玉米蛋餅 大杯冰紅茶"),
    asst_call("call_1","add_riceball",{"flavor":"咖哩嫩雞","rice":"紫米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 紫米咖哩嫩雞飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"玉米"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 玉米蛋餅",2),
    asst_call("call_3","add_drink",{"flavor":"精選紅茶","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰精選紅茶",3),
    asst("好，咖哩嫩雞紫米飯糰、玉米蛋餅跟大杯冰紅茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_4","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_4",order_num,135,3,"take-out","cash"),
    asst(f"好，總共 135 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_DRINK,T_FINAL])); order_num+=1

# 52: 4品項全齊連續call
msgs = [sys_msg(), user("蔥蛋豆芽白米飯糰 培根蛋餅 起司蛋吐司 大杯溫豆漿"),
    asst_call("call_1","add_riceball",{"flavor":"蔥蛋豆芽","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米蔥蛋豆芽飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"培根"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 培根蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"吐司","flavor":"起司蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 起司蛋吐司",3),
    asst_call("call_4","add_drink",{"flavor":"有糖豆漿","size":"大杯","temp":"溫"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 大杯溫有糖豆漿",4),
    asst("好，蔥蛋豆芽白米飯糰、培根蛋餅、起司蛋吐司跟大杯溫豆漿～還需要什麼嗎？"),
    user("就這樣 內用 Line Pay"),
    asst_call("call_5","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_5",order_num,175,4,"dine-in","line_pay"),
    asst(f"好，總共 175 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_DRINK,T_FINAL])); order_num+=1

# 53: 5品項全齊連續call
msgs = [sys_msg(), user("醬燒里肌混米飯糰 沙茶豬肉蛋餅 豬肉蛋漢堡 煎餃 大杯冰鮮奶茶"),
    asst_call("call_1","add_riceball",{"flavor":"醬燒里肌","rice":"混米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 混米醬燒里肌飯糰",1),
    asst_call("call_2","add_egg_pancake",{"flavor":"沙茶豬肉"}),
    tool_resp("call_2",True,"egg_pancake_1","已加入 1份 沙茶豬肉蛋餅",2),
    asst_call("call_3","add_carrier",{"carrier":"漢堡","flavor":"豬肉蛋"}),
    tool_resp("call_3",True,"carrier_1","已加入 1份 豬肉蛋漢堡",3),
    asst_call("call_4","add_snack",{"flavor":"煎餃(8顆)"}),
    tool_resp("call_4",True,"snack_1","已加入 1份 煎餃(8顆)",4),
    asst_call("call_5","add_drink",{"flavor":"純鮮奶茶","size":"大杯","temp":"冰"}),
    tool_resp("call_5",True,"drink_1","已加入 1份 大杯冰純鮮奶茶",5),
    asst("好，醬燒里肌混米飯糰、沙茶豬肉蛋餅、豬肉蛋漢堡、煎餃跟大杯冰鮮奶茶～還需要什麼嗎？"),
    user("沒了 外帶 現金"),
    asst_call("call_6","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_6",order_num,260,5,"take-out","cash"),
    asst(f"好，總共 260 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_EGG,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 54: 4品項全齊連續call
msgs = [sys_msg(), user("素料飯糰白米 黑糖饅頭 香酥脆薯 中杯冰綠茶"),
    asst_call("call_1","add_riceball",{"flavor":"素料","rice":"白米"}),
    tool_resp("call_1",True,"riceball_1","已加入 1份 白米素料飯糰",1),
    asst_call("call_2","add_carrier",{"carrier":"饅頭","flavor":"黑糖饅頭"}),
    tool_resp("call_2",True,"carrier_1","已加入 1份 黑糖饅頭",2),
    asst_call("call_3","add_snack",{"flavor":"香酥脆薯"}),
    tool_resp("call_3",True,"snack_1","已加入 1份 香酥脆薯",3),
    asst_call("call_4","add_drink",{"flavor":"無糖清香綠茶","size":"中杯","temp":"冰"}),
    tool_resp("call_4",True,"drink_1","已加入 1份 中杯冰無糖清香綠茶",4),
    asst("好，素料白米飯糰、黑糖饅頭、香酥脆薯跟中杯冰綠茶～還需要什麼嗎？"),
    user("不用 外帶 付現"),
    asst_call("call_5","finalize_order",{"dine_type":"外帶","payment_method":"現金"}),
    final_resp("call_5",order_num,125,4,"take-out","cash"),
    asst(f"好，總共 125 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_RICEBALL,T_CARRIER,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# 55: 3品項全齊連續call(套餐)
msgs = [sys_msg(), user("套餐A 冰的 無骨雞排 大杯冰鮮奶咖啡"),
    asst_call("call_1","add_combo",{"combo_name":"套餐A","temp":"冰"}),
    tool_resp("call_1",True,"combo_1","已加入 套餐A 總匯三明治+薯條+雞塊*2+紅茶(大)",1),
    asst_call("call_2","add_snack",{"flavor":"無骨雞排"}),
    tool_resp("call_2",True,"snack_1","已加入 1份 無骨雞排",2),
    asst_call("call_3","add_drink",{"flavor":"純鮮奶咖啡","size":"大杯","temp":"冰"}),
    tool_resp("call_3",True,"drink_1","已加入 1份 大杯冰純鮮奶咖啡",3),
    asst("好，套餐A、無骨雞排跟大杯冰鮮奶咖啡～還需要什麼嗎？"),
    user("沒了 內用 Line Pay"),
    asst_call("call_4","finalize_order",{"dine_type":"內用","payment_method":"Line Pay"}),
    final_resp("call_4",order_num,235,3,"dine-in","line_pay"),
    asst(f"好，總共 235 元，取餐號碼 {order_num} 號，謝謝！")]
rows.append(entry(msgs,[T_COMBO,T_SNACK,T_DRINK,T_FINAL])); order_num+=1

# Write output
outpath = r"C:\Users\User\Desktop\ai-ordering-system\training_data\category_e3_multi_item.jsonl"
with open(outpath, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(r + "\n")
print(f"Written {len(rows)} entries")

# Validate
with open(outpath, "r", encoding="utf-8") as f:
    lines = f.readlines()
errors = []
for i, line in enumerate(lines, 1):
    try:
        d = json.loads(line)
        msgs = d["messages"]
        for m in msgs:
            if "tool_calls" in m and m.get("tool_calls"):
                if len(m["tool_calls"]) != 1:
                    errors.append(f"Line {i}: tool_calls has {len(m['tool_calls'])} calls")
                tc = m["tool_calls"][0]
                args = tc["function"]["arguments"]
                if not isinstance(args, dict):
                    errors.append(f"Line {i}: arguments is {type(args).__name__}, not dict")
        has_final = any(
            "tool_calls" in m and m.get("tool_calls") and m["tool_calls"][0]["function"]["name"] == "finalize_order"
            for m in msgs
        )
        if not has_final:
            errors.append(f"Line {i}: missing finalize_order")
    except Exception as e:
        errors.append(f"Line {i}: JSON parse error: {e}")

if errors:
    print("ERRORS:")
    for e in errors:
        print(f"  {e}")
else:
    print(f"All {len(lines)} entries validated OK")
    print("  - All arguments are JSON objects")
    print("  - All tool_calls have exactly 1 call")
    print("  - All entries have finalize_order")
