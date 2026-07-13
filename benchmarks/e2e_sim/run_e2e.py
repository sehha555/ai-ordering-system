# benchmarks/e2e_sim/run_e2e.py
"""端到端模擬點餐回歸套件 — 自動判分版 dogfood loop

跑 scenario YAML 的多輪腳本打 /api/text-chat（同 tools/order_sim.py 管道），
結束後查 orders.db 該 session 的訂單，比對 expected（品項+數量+總價+內用外帶）。
與 unified benchmark 的差異：這裡量測「整條 pipeline 的出單正確率」
（LLM tag + 後端防護 + 結帳狀態機），不是單測 LLM 行為。

用法（backend 8001 + llama-server 1234 需在跑）：
    uv run python -m benchmarks.e2e_sim.run_e2e                # 全部跑 1 次
    uv run python -m benchmarks.e2e_sim.run_e2e --repeat 3     # 穩定度模式
    uv run python -m benchmarks.e2e_sim.run_e2e --filter b12   # 只跑 b12 系列
"""

import argparse
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

DEFAULT_BASE = "http://localhost:8001"
SCENARIO_DIR = Path(__file__).parent / "scenarios"
REPORT_DIR = Path(__file__).parents[1] / "reports"
DB_PATH = Path(__file__).parents[2] / "orders.db"


def send_turn(client: httpx.Client, base: str, session_id: str, text: str) -> None:
    """送一輪對話並 drain 整條 SSE stream（不解析內容，只等它跑完）"""
    with client.stream(
        "POST", f"{base}/api/text-chat", json={"text": text, "session_id": session_id}
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} on turn: {text}")
        for _ in resp.iter_lines():
            pass


def fetch_order(session_id: str) -> dict | None:
    """查該 session 最新一筆訂單 payload；無訂單回 None"""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT order_payload_json FROM orders WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None


def judge(expected: dict, order: dict | None) -> list[str]:
    """比對 expected 與實際訂單，回傳問題清單（空 = 通過）"""
    problems: list[str] = []
    if order is None:
        return ["訂單不存在（整單蒸發或結帳未完成）"]

    if "total" in expected and order.get("total_price") != expected["total"]:
        problems.append(f"total: 預期 {expected['total']}，實際 {order.get('total_price')}")
    if "dine_type" in expected and order.get("dine_type") != expected["dine_type"]:
        problems.append(f"dine_type: 預期 {expected['dine_type']}，實際 {order.get('dine_type')}")
    if "payment" in expected and order.get("payment_method") != expected["payment"]:
        problems.append(f"payment: 預期 {expected['payment']}，實際 {order.get('payment_method')}")
    if (
        "price_pending" in expected
        and bool(order.get("price_pending")) != expected["price_pending"]
    ):
        problems.append(
            f"price_pending: 預期 {expected['price_pending']}，實際 {order.get('price_pending')}"
        )

    display = order.get("items_display") or []
    exp_items = expected.get("items")
    if exp_items is not None:
        # 每個實際品項須被恰一個 expected 條目認領（防幻覺多出品項）；
        # 每個 expected 條目認領到的數量總和須等於 qty（分行入車視為等價）
        claimed = [False] * len(display)
        for exp in exp_items:
            sub = exp["name"]
            qty = exp.get("qty", 1)
            got = 0
            for i, it in enumerate(display):
                if not claimed[i] and sub in it.get("name", ""):
                    claimed[i] = True
                    got += int(it.get("quantity", 1) or 1)
            if got != qty:
                problems.append(f"品項「{sub}」: 預期 x{qty}，實際 x{got}")
        for i, it in enumerate(display):
            if not claimed[i]:
                problems.append(f"多出品項: {it.get('name')} x{it.get('quantity')}")
    return problems


def run_scenario(client: httpx.Client, base: str, scenario: dict, run_idx: int) -> dict:
    """跑一次 scenario，回傳 {passed, problems, session_id}"""
    session_id = f"e2e-{scenario['id']}-{run_idx}-{uuid.uuid4().hex[:6]}"
    try:
        for turn in scenario["script"]:
            send_turn(client, base, session_id, turn)
    except (httpx.HTTPError, RuntimeError) as e:
        return {"passed": False, "problems": [f"連線/HTTP 錯誤: {e}"], "session_id": session_id}
    problems = judge(scenario.get("expected", {}), fetch_order(session_id))
    return {"passed": not problems, "problems": problems, "session_id": session_id}


def load_scenarios(filter_str: str | None) -> list[dict]:
    scenarios: list[dict] = []
    for f in sorted(SCENARIO_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        scenarios.extend(data)
    if filter_str:
        scenarios = [s for s in scenarios if filter_str in s["id"]]
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E 模擬點餐回歸套件")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--repeat", type=int, default=1, help="每個 scenario 跑 N 次測穩定度")
    parser.add_argument("--filter", default=None, help="只跑 id 含此字串的 scenario")
    args = parser.parse_args()

    scenarios = load_scenarios(args.filter)
    if not scenarios:
        print("沒有符合的 scenario")
        sys.exit(1)

    # readyz 前置檢查
    try:
        r = httpx.get(f"{args.base}/readyz", timeout=10)
        checks = r.json().get("checks", {})
        if checks.get("llm") != "ok":
            print(f"[中止] backend LLM 檢查未過: {checks}")
            sys.exit(1)
    except httpx.HTTPError as e:
        print(f"[中止] backend 未就緒: {e}")
        sys.exit(1)

    results: dict[str, dict] = {}
    start = time.time()
    with httpx.Client(timeout=120) as client:
        for sc in scenarios:
            runs = [run_scenario(client, args.base, sc, i) for i in range(args.repeat)]
            ok = sum(1 for r in runs if r["passed"])
            results[sc["id"]] = {
                "known_fail": bool(sc.get("known_fail")),
                "passed": ok,
                "total": len(runs),
                "runs": runs,
            }
            mark = "✓" if ok == len(runs) else ("△" if ok else "✗")
            kf = "[known_fail] " if sc.get("known_fail") else ""
            print(f"{mark} {kf}{sc['id']}: {ok}/{len(runs)}")
            for r in runs:
                for p in r["problems"]:
                    print(f"    - {p}")

    active = {k: v for k, v in results.items() if not v["known_fail"]}
    known = {k: v for k, v in results.items() if v["known_fail"]}
    act_runs = sum(v["total"] for v in active.values())
    act_pass = sum(v["passed"] for v in active.values())
    kn_pass = sum(v["passed"] for v in known.values())
    kn_runs = sum(v["total"] for v in known.values())

    print()
    print(f"主套件通過率: {act_pass}/{act_runs} ({act_pass / act_runs:.1%})" if act_runs else "")
    if kn_runs:
        print(f"known_fail 追蹤: {kn_pass}/{kn_runs} 通過（通過代表架構問題有進展）")
    print(f"耗時 {time.time() - start:.0f}s")

    REPORT_DIR.mkdir(exist_ok=True)
    report_path = REPORT_DIR / f"e2e_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(
        json.dumps(
            {"pass": act_pass, "runs": act_runs, "known_fail_pass": kn_pass, "results": results},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"報告: {report_path}")
    sys.exit(0 if act_pass == act_runs else 2)


if __name__ == "__main__":
    main()
