"""文字模擬完整點餐流程 — 打 /api/text-chat SSE 端點，跳過麥克風/ASR。

用途：不需語音、不需 TTS service，純文字驗證 LLM→工具→結帳這條主鏈會不會動。
跑法：uv run python scripts/simulate_order.py
"""

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8001"

# 多組情境，跑法：uv run python scripts/simulate_order.py <情境名>
SCENARIOS = {
    "full": [
        "你好",
        "我要一個鮪魚飯糰",  # 可能被追問米種
        "紫米 要辣",
        "再給我一個起司蛋餅",
        "一杯紅茶 大杯 冰的",
        "好了 結帳",
        "內用",
        "現金",
    ],
    # 售完情境：起司蛋餅已設售完，客人點到 → 店員應說沒有，再改點別的
    "soldout": [
        "你好",
        "我要一個起司蛋餅",  # 售完，預期店員告知缺貨
        "那給我一個鮪魚飯糰 白米",  # 改點別的
        "結帳",
        "外帶",
        "現金",
    ],
    # 改單情境：加兩個單品 → 指名刪掉其中一個 → 結帳，看購物車有沒有正確跟著變
    # 用單品避免「點兩份要不要不同口味」的追問打斷
    "modify": [
        "你好",
        "一個鮪魚飯糰 紫米 不要辣",  # 加飯糰
        "再一杯紅茶 中杯 冰的",  # 加紅茶（此時兩項）
        "飯糰不要了",  # 指名刪飯糰，應只剩紅茶
        "結帳",
        "內用",
        "現金",
    ],
    # 換品項情境：點 A → 要求換成 B，測 [REMOVE]+[ADD] 一起發的可靠度
    # 高風險：模型常只發其中一個 tag，導致舊品項沒刪或新品項沒加
    "replace": [
        "你好",
        "一個鮪魚飯糰 紫米 不要辣",  # 先點飯糰
        "飯糰改成起司蛋餅",  # 換品項：應刪飯糰、加起司蛋餅
        "結帳",
        "外帶",
        "現金",
    ],
    # 改數量情境：用點心（薯餅）避免飯糰「兩份要不要不同口味」的追問
    "qty": [
        "你好",
        "我要三個薯餅",  # 一次點三份
        "薯餅改成一個",  # 改數量 3→1
        "結帳",
        "內用",
        "現金",
    ],
    # 套餐情境：套餐走 combo_status / check_combo_required，跟單品不同路徑
    "combo": [
        "你好",
        "我要一個套餐一",  # 點套餐，可能追問飲料/溫度
        "紅茶 冰的",  # 補飲料
        "結帳",
        "內用",
        "現金",
    ],
    # 客製化待確認：加料類客製 → 價格待確認 + 不能先付
    "custom": [
        "你好",
        "一個鮪魚飯糰 紫米 加起司",  # 加料客製 → 應標待確認
        "結帳",
        "內用",  # 有 pending → 應跳過付款、建待店員結算單、不收款
    ],
}


def parse_sse(raw: str):
    """把一段 SSE 文字切成 (event, data_dict) list。"""
    events = []
    cur_event = None
    for line in raw.splitlines():
        if line.startswith("event:"):
            cur_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            payload = line[len("data:") :].strip()
            try:
                data = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                data = {"_raw": payload}
            events.append((cur_event, data))
            cur_event = None
    return events


def send_turn(client: httpx.Client, session: str, text: str):
    """送一句話，回傳 (ai_reply, cart_items, total, has_pending, order_complete, err)。"""
    ai_reply = ""
    cart_items = None
    total = None
    has_pending = False
    order_done = None
    err = None

    with client.stream(
        "POST",
        f"{BASE}/api/text-chat",
        json={"text": text, "session_id": session},
        timeout=120,
    ) as resp:
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            # SSE 事件以空行分隔，逐段解析（保留未完成尾段）
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                for ev, data in parse_sse(block + "\n\n"):
                    if ev == "tts_text":
                        ai_reply = data.get("text", ai_reply)
                    elif ev == "cart_update":
                        cart_items = data.get("items")
                        total = data.get("total")
                        # has_pending 由 items 的 price_pending derive（後端不另送）
                        has_pending = any(
                            (it or {}).get("price_pending") for it in (cart_items or [])
                        )
                    elif ev == "order_complete":
                        order_done = data
                    elif ev == "error":
                        err = data.get("message")
    return ai_reply, cart_items, total, has_pending, order_done, err


def fmt_cart(items, total, has_pending=False):
    if not items:
        return "（空）"
    lines = []
    for it in items:
        if isinstance(it, dict):
            name = it.get("name") or it.get("display") or json.dumps(it, ensure_ascii=False)
            qty = it.get("quantity") or it.get("qty") or ""
            if it.get("price_pending"):
                price_str = "  價格待確認"
            else:
                price = it.get("price", "")
                price_str = f"  ${price}" if price != "" else ""
            lines.append(f"{name} x{qty}{price_str}")
        else:
            lines.append(str(it))
    body = "；".join(lines)
    total_str = "待確認" if has_pending else f"${total}"
    return f"{body}  ｜ 小計 {total_str}" if total is not None else body


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "full"
    if scenario not in SCENARIOS:
        print(f"未知情境 '{scenario}'，可選：{', '.join(SCENARIOS)}", file=sys.stderr)
        sys.exit(2)
    utterances = SCENARIOS[scenario]
    session = f"sim-{scenario}-001"

    print("=" * 60)
    print(f"文字模擬點餐 — 情境：{scenario}  session：{session}")
    print("=" * 60)
    with httpx.Client() as client:
        for i, text in enumerate(utterances, 1):
            print(f"\n[{i}] 客人：{text}")
            t0 = time.perf_counter()
            ai, items, total, has_pending, done, err = send_turn(client, session, text)
            dt = time.perf_counter() - t0
            if err:
                print(f"    ✗ 錯誤：{err}")
            print(f"    店員：{ai or '（無文字回覆）'}")
            if items is not None:
                print(f"    購物車：{fmt_cart(items, total, has_pending)}")
            if done:
                print(f"    >>> 結帳完成：{json.dumps(done, ensure_ascii=False)}")
            print(f"    （耗時 {dt:.2f}s）")
    print("\n" + "=" * 60)
    print("流程結束")


if __name__ == "__main__":
    try:
        main()
    except httpx.ConnectError:
        print("連不上後端 127.0.0.1:8001 — 後端還沒起來或掛了", file=sys.stderr)
        sys.exit(1)
