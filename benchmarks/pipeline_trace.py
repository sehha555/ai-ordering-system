"""
Pipeline Trace — 跑指定場景，印出每一步的完整 payload。
用法: uv run python -m benchmarks.pipeline_trace
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

# 確保專案根目錄在 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dm.tool_registry import ToolRegistry
from src.dm.system_prompts import SystemPromptBuilder

# ── 設定 ──
LLM_URL = "http://127.0.0.1:1234/v1/chat/completions"
SCENARIO_FILE = ROOT / "benchmarks" / "test_data" / "llm" / "test_scenarios.json"

# 要 trace 的失敗場景（2026-04-29 baseline 90% 跑出來的 7 個 fail）
TRACE_IDS = [
    "u_riceball_multi_round",
    "u_carrier_missing",
    "u_intent_mushroom_noodle",
    "u_combo_b_toast",
    "sold_out_combo_component",
    "swap_riceball",
    "swap_nonexistent_remove_but_add",
]

# Text Tag 正則（與 voice_router 一致）
_ADD_RE = re.compile(r"\[ADD:([^\]]+)\]")
_QUERY_RE = re.compile(r"\[QUERY(?::([^\]]*))?\]")
_REMOVE_RE = re.compile(r"\[REMOVE:(.+?)\]")
_CHECKOUT_RE = re.compile(r"\[CHECKOUT\]")


def load_scenarios():
    with open(SCENARIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_system_prompt():
    builder = SystemPromptBuilder()
    return builder.build()


def build_context_message(session_context: dict) -> str:
    """模擬 benchmark adapter 注入的購物車/售完 context。"""
    parts = []
    cart = session_context.get("cart_items", [])
    if cart:
        parts.append("購物車：" + "、".join(cart))
    else:
        parts.append("購物車：空")

    sold = session_context.get("sold_out", [])
    if sold:
        parts.append("售完：" + "、".join(sold))

    return "\n".join(parts)


def call_llm(messages: list) -> dict:
    """呼叫 llama-server，回傳 raw response。"""
    payload = {
        "model": "qwen3.5-9b",
        "messages": messages,
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.01,
        "max_tokens": 512,
        "tools": [],
    }
    t0 = time.time()
    resp = httpx.post(LLM_URL, json=payload, timeout=30)
    latency = time.time() - t0
    data = resp.json()
    return {
        "content": data["choices"][0]["message"]["content"],
        "tokens": data.get("usage", {}),
        "latency_s": round(latency, 3),
    }


def parse_tags(raw_text: str) -> dict:
    """解析 text tags，回傳結構化結果。"""
    adds = []
    for m in _ADD_RE.finditer(raw_text):
        parts = m.group(1).split("|")
        item_name = parts[0].strip()
        kwargs = {"name": item_name}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "qty":
                    kwargs["quantity"] = int(v)
                elif k in ("rice", "size", "temp", "flavor", "customization"):
                    kwargs[k] = v
                elif k in ("spicy", "extra_egg", "large", "heavy"):
                    kwargs[k] = v.lower() == "true"
        adds.append({"action": "ADD", "args": kwargs})

    queries = []
    for m in _QUERY_RE.finditer(raw_text):
        cat = m.group(1) or ""
        queries.append({"action": "QUERY", "category": cat.strip()})

    removes = []
    for m in _REMOVE_RE.finditer(raw_text):
        removes.append({"action": "REMOVE", "target": m.group(1).strip()})

    checkout = bool(_CHECKOUT_RE.search(raw_text))

    # 清除 tags 後的純文字
    cleaned = _ADD_RE.sub("", raw_text)
    cleaned = _QUERY_RE.sub("", cleaned)
    cleaned = _REMOVE_RE.sub("", cleaned)
    cleaned = _CHECKOUT_RE.sub("", cleaned).strip()

    return {
        "adds": adds,
        "queries": queries,
        "removes": removes,
        "checkout": checkout,
        "cleaned_text": cleaned,
    }


def execute_tools(parsed: dict, tool_registry: ToolRegistry) -> list:
    """執行解析出的 tool calls，回傳結果。"""
    results = []

    for add in parsed["adds"]:
        args = add["args"]
        try:
            result = tool_registry.add_item(**args)
        except Exception as e:
            result = {"ok": False, "message": f"Exception: {e}"}
        results.append({"action": "ADD", "input": args, "result": result})

    for q in parsed["queries"]:
        try:
            result = tool_registry.query_menu(category=q["category"])
        except Exception as e:
            result = {"ok": False, "message": f"Exception: {e}"}
        results.append({"action": "QUERY", "input": q, "result": result})

    return results


def trace_scenario(scenario: dict):
    """跑一個場景的完整 pipeline trace。"""
    sid = scenario["id"]
    desc = scenario.get("description", "")
    ctx = scenario.get("session_context", {})
    user_msg = scenario["messages"][-1]["content"]
    expected_tools = scenario.get("expected_tools", [])
    expected_contains = scenario.get("expected_response_contains", [])
    expected_behavior = scenario.get("expected_behavior", "")

    print(f"\n{'=' * 70}")
    print(f"  {sid}: {desc}")
    print(f"{'=' * 70}")

    # ── Step 1: 期望 ──
    print("\n[EXPECTED]")
    print(f"  tools: {expected_tools}")
    print(f"  response_contains: {expected_contains}")
    print(f"  behavior: {expected_behavior}")

    # ── Step 2: System Prompt ──
    sold_out = ctx.get("sold_out", [])
    sold_out_cats = ctx.get("sold_out_categories", {})
    system_prompt = build_system_prompt()
    prompt_lines = system_prompt.count("\n") + 1
    prompt_chars = len(system_prompt)
    print("\n[STEP 1] System Prompt")
    print(f"  lines: {prompt_lines}, chars: {prompt_chars}")
    # 只印售完相關段落
    if sold_out:
        print(f"  sold_out injected: {sold_out}")
    if sold_out_cats:
        print(f"  sold_out_categories: {sold_out_cats}")

    # ── Step 3: 組裝 messages ──
    messages = [{"role": "system", "content": system_prompt}]

    # 注入 priming demos（從 adapter 的邏輯）
    from src.dm.tool_priming import get_priming_messages

    priming = get_priming_messages()
    messages.extend(priming)

    # 注入 context（購物車/售完）
    context_text = build_context_message(ctx)

    # History（如果有多輪）
    for msg in scenario["messages"][:-1]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 最後一條 user message（帶 context prefix）
    final_user = f"# 當前狀態\n{context_text}\n\n{user_msg}"
    messages.append({"role": "user", "content": final_user})

    print("\n[STEP 2] LLM Input")
    print(
        f"  total messages: {len(messages)} (1 system + {len(priming)} priming + {len(scenario['messages'])} dialogue)"
    )
    print(f"  cart: {ctx.get('cart_items', [])}")
    print(f'  user: "{user_msg}"')

    # ── Step 4: 呼叫 LLM ──
    print("\n[STEP 3] LLM Call...")
    llm_result = call_llm(messages)
    raw_content = llm_result["content"]
    print(f"  latency: {llm_result['latency_s']}s")
    print(f"  tokens: {llm_result['tokens']}")
    print(f'  raw output: "{raw_content}"')

    # ── Step 5: Tag 解析 ──
    parsed = parse_tags(raw_content)
    print("\n[STEP 4] Tag Parse")
    print(f"  ADDs: {parsed['adds']}")
    print(f"  QUERYs: {parsed['queries']}")
    print(f"  REMOVEs: {parsed['removes']}")
    print(f"  CHECKOUT: {parsed['checkout']}")
    print(f'  cleaned_text: "{parsed["cleaned_text"]}"')

    # ── Step 6: Tool 執行 ──
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.session_store import InMemorySessionStore

    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    tool_registry = ToolRegistry(dm, store)
    tool_registry.set_session_id("trace_test")
    exec_results = execute_tools(parsed, tool_registry)
    print("\n[STEP 5] Tool Execution")
    if not exec_results:
        print("  (no tools executed)")
    for er in exec_results:
        ok = er["result"].get("ok", "N/A")
        msg = er["result"].get("message", "")
        price = er["result"].get("price", "")
        print(f"  {er['action']}: input={er['input']}")
        print(f'    ok={ok}, message="{msg}", price={price}')

    # ── Step 7: Verdict ──
    print("\n[STEP 6] Verdict")
    # 檢查 expected_contains
    response_text = parsed["cleaned_text"]
    # 如果 tool 失敗，實際回覆會用 tool 的 message
    if exec_results:
        failed = [r for r in exec_results if not r["result"].get("ok")]
        if failed:
            response_text += " " + " ".join(r["result"].get("message", "") for r in failed)

    keyword_hits = []
    keyword_misses = []
    for kw in expected_contains:
        if kw in response_text or kw in raw_content:
            keyword_hits.append(kw)
        else:
            keyword_misses.append(kw)

    actual_tool_names = []
    for add in parsed["adds"]:
        actual_tool_names.append("add_item")
    for _ in parsed["queries"]:
        actual_tool_names.append("query_menu")

    tools_match = sorted(actual_tool_names) == sorted(expected_tools)

    print(f"  expected_tools: {expected_tools}")
    print(f"  actual_tools:   {actual_tool_names}")
    print(f"  tools_match: {tools_match}")
    print(f"  keyword_hits: {keyword_hits}")
    print(f"  keyword_misses: {keyword_misses}")

    passed = tools_match and len(keyword_misses) == 0
    status = "PASS" if passed else "FAIL"
    print(f"  => {status}")

    if not passed:
        # 診斷瓶頸在哪一步
        print("\n[DIAGNOSIS]")
        if not tools_match and len(actual_tool_names) > len(expected_tools):
            print("  LLM 不該出 tag 但出了 → 模型問題（應該追問但直接下單）")
        elif not tools_match and len(actual_tool_names) < len(expected_tools):
            print("  LLM 該出 tag 但沒出 → 模型問題（應該下單但只回文字）")
        if keyword_misses:
            # 檢查是模型沒提到，還是 tool 回覆沒帶
            for kw in keyword_misses:
                if kw in raw_content:
                    print(f'  "{kw}" 在 raw output 有，但被 tag/template 吃掉')
                else:
                    print(f'  "{kw}" 模型完全沒提到 → prompt 不夠或模型能力限制')

    return {"id": sid, "passed": passed, "status": status}


def main():
    scenarios = load_scenarios()
    target = {s["id"]: s for s in scenarios if s["id"] in TRACE_IDS}

    print(f"Pipeline Trace — {len(target)} scenarios")
    print(f"LLM: {LLM_URL}")

    results = []
    for sid in TRACE_IDS:
        if sid not in target:
            print(f"\n[SKIP] {sid} not found in scenarios")
            continue
        r = trace_scenario(target[sid])
        results.append(r)

    # 總結
    print(f"\n{'=' * 70}")
    print("  SUMMARY")
    print(f"{'=' * 70}")
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"  {passed}/{total} passed")
    for r in results:
        mark = "OK" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['id']}")


if __name__ == "__main__":
    main()
