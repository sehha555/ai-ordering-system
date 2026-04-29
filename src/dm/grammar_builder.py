"""Grammar Builder — GBNF for llama.cpp grammar-constrained decoding.

實驗結論（2026-04-29）：寬鬆版（品項名自由，只欄位 value enum）+3% benchmark
（90% → 93%）。嚴格版（品項名 enum 全列）-2%（90% → 88%），原因：列舉 100+
品項名讓 ADD path token 機率密度過高，nudge 模型偏向直接 ADD 而非純文字追問。

設計：
- 結構約束：tag 格式嚴（[ADD/QUERY/REMOVE/CHECKOUT]）
- 欄位 value enum：rice/temp/size/noodle 列合法值，提高正確 ADD 的 token 穩定性
- 品項名自由：text 形式，靠後端 _resolve_item_name 模糊匹配
- 純文字逃生口：root 允許自由文字 segment，模型可純文字追問/拒絕
"""

from __future__ import annotations

from typing import Optional

_GRAMMAR_CACHE: Optional[str] = None

_GRAMMAR = """# Grammar for order tags (text_tag mode)
# 結構約束 + 欄位 value enum，品項名自由（後端 resolver 處理）

root ::= segment+
segment ::= text-segment | tag

text-segment ::= [^\\[]+

tag ::= add-tag | query-tag | remove-tag | checkout-tag

checkout-tag ::= "[CHECKOUT]"

query-tag ::= "[QUERY" query-cat-suffix? "]"
query-cat-suffix ::= ":" [^\\]]+

remove-tag ::= "[REMOVE:" [^\\]]+ "]"

# ADD：品項名自由，欄位 value enum 嚴
add-tag ::= "[ADD:" item-name add-params "]"
item-name ::= [^|\\]]+
add-params ::= ("|" param)*
param ::= rice-param | size-param | temp-param | flavor-param | noodle-param | qty-param | customization-param

rice-param ::= "rice=" rice-value
rice-value ::= "白米" | "紫米" | "混米"

size-param ::= "size=" size-value
size-value ::= "中杯" | "大杯" | "中" | "大" | "薄片" | "厚片"

temp-param ::= "temp=" temp-value
temp-value ::= "冰" | "溫"

flavor-param ::= "flavor=" flavor-value
flavor-value ::= [^|\\]]+

noodle-param ::= "noodle=" noodle-value
noodle-value ::= "油麵" | "烏龍麵" | "烏龍"

qty-param ::= "qty=" digit+
digit ::= [0-9]

customization-param ::= "customization=" customization-text
customization-text ::= [^|\\]]+
"""


def build_grammar() -> str:
    """回傳 GBNF 字串，模組層級 cache。"""
    global _GRAMMAR_CACHE
    if _GRAMMAR_CACHE is None:
        _GRAMMAR_CACHE = _GRAMMAR
    return _GRAMMAR_CACHE


def clear_cache() -> None:
    """清除快取（測試用）。"""
    global _GRAMMAR_CACHE
    _GRAMMAR_CACHE = None
