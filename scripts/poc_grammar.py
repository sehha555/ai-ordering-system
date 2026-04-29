"""Phase 1A PoC：用 production grammar (full menu) 跑重點失敗 case。

重點驗證：
1. Grammar load 沒爆
2. 失敗模式 1（起司蛋無載體）→ 期望 grammar 強制 model 不能直接 ADD「起司蛋」（不在任何 enum）
3. 失敗模式 2（套餐 B 厚片無口味）→ grammar 允許 combo flavor optional，看 model 是否仍追問
4. 多個 case baseline vs grammar 行為對比
"""

from __future__ import annotations

import sys

import httpx

from src.dm.grammar_builder import build_grammar
from src.dm.system_prompts import SystemPromptBuilder
from src.dm.tool_priming import get_priming_messages

LLAMA_SERVER_URL = "http://127.0.0.1:1234/v1/chat/completions"


def call_llama(
    system_prompt: str, priming: list[dict], user_text: str, with_grammar: bool, grammar: str
) -> dict:
    messages = [{"role": "system", "content": "/no_think\n" + system_prompt}]
    messages.extend(priming)
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": "qwen3.5-9b",
        "messages": messages,
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "max_tokens": 200,
    }
    if with_grammar:
        payload["grammar"] = grammar
    r = httpx.post(LLAMA_SERVER_URL, json=payload, timeout=120.0)
    r.raise_for_status()
    return r.json()


def run_case(
    label: str,
    system_prompt: str,
    priming: list[dict],
    user_text: str,
    with_grammar: bool,
    grammar: str,
) -> None:
    print(f"\n[{label}] grammar={with_grammar}")
    print(f"  user: {user_text}")
    try:
        resp = call_llama(system_prompt, priming, user_text, with_grammar, grammar)
        content = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage", {})
        print(
            f"  tokens: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}"
        )
        print(f"  content: {content!r}")
    except httpx.HTTPStatusError as e:
        print(f"  HTTP {e.response.status_code}: {e.response.text[:300]}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    print("Loading production system prompt + grammar...")
    builder = SystemPromptBuilder()
    system_prompt = builder.build()
    priming = get_priming_messages()
    grammar = build_grammar()
    print(f"  system prompt: {len(system_prompt)} chars")
    print(f"  priming: {len(priming)} messages")
    print(f"  grammar: {len(grammar)} chars, {grammar.count(chr(10))} lines")

    # 重點：對應 benchmark 已知失敗 case
    cases = [
        ("normal_riceball", "一個鮪魚飯糰白米"),
        ("missing_rice", "一個鮪魚飯糰"),
        ("cheese_egg_no_carrier", "一個起司蛋"),  # 失敗模式 1
        ("combo_b_no_flavor", "一個套餐B 冰的"),  # 失敗模式 2
        ("not_in_menu", "一杯珍珠奶茶"),
        ("checkout", "好了 買單"),
        ("query_drinks", "有什麼飲料"),
        ("iron_noodle_complete", "一個黑椒鐵板麵 烏龍"),
    ]

    print("\n" + "=" * 60)
    print(">>> 不帶 grammar（baseline）")
    print("=" * 60)
    for label, text in cases:
        run_case(label, system_prompt, priming, text, with_grammar=False, grammar=grammar)

    print("\n" + "=" * 60)
    print(">>> 帶 grammar")
    print("=" * 60)
    for label, text in cases:
        run_case(label, system_prompt, priming, text, with_grammar=True, grammar=grammar)

    return 0


if __name__ == "__main__":
    sys.exit(main())
