"""分類查詢短路測試

客人問「有什麼饅頭」時 LLM 憑記憶背誦全部 19 項，TTS 要唸 10-21s。
改由後端查菜單直接回「N 種 + 三個代表」。複合句（查詢+點餐同句）
必須照舊放行給 LLM，否則點餐部分會整句被吞掉（b14-01）。
"""

import pytest

from src.api.voice_router import _build_category_reply, _match_category_inquiry


def _items(*specs):
    """(品名, 是否有貨) → query_menu items 格式"""
    return [{"name": name, "available": available} for name, available in specs]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("有什麼饅頭", "饅頭"),
        ("饅頭有什麼", "饅頭"),
        ("有什麼包子", "饅頭"),
        ("有什麼飲料", "飲品"),
        ("飲料有什麼", "飲品"),
        ("有哪些飲料", "飲品"),
        ("喝的有什麼", "飲品"),
        ("有什麼喝的", "飲品"),
        ("你們有哪些套餐", "套餐"),
        ("蛋餅有什麼口味", "蛋餅"),
        ("請問有什麼吐司", "吐司"),
    ],
)
def test_category_inquiry_matched(text, expected):
    assert _match_category_inquiry(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "你們飲料有什麼 我先要一個起司蛋餅",  # b14-01 複合句：攔截會吞掉點餐
        "飲料有什麼 有豆漿嗎",  # b14-11 查詢+存在性複合句
        "有賣咖啡嗎",  # 存在性查詢走步驟 5
        "有什麼",  # 沒指定分類 → 交 LLM
        "豆漿有什麼",  # 品項不是分類
        "有什麼吃的",  # 非菜單分類詞
    ],
)
def test_non_category_inquiry_falls_through(text):
    assert _match_category_inquiry(text) is None


def test_many_items_reports_count_and_three_samples():
    """品項多 → 報數量 + 三個代表，不整串列出"""
    items = _items(*[(f"包{i}", True) for i in range(19)])
    reply = _build_category_reply("饅頭", items)

    assert reply == "饅頭有19種，像是包0、包1、包2，要聽別的嗎？"


def test_cup_sizes_counted_as_one_item():
    """飲品的中/大杯是同一種，報數量與代表品項都不重複計"""
    items = _items(
        ("有糖豆漿(中)", True),
        ("有糖豆漿(大)", True),
        ("無糖豆漿(中)", True),
        ("無糖豆漿(大)", True),
        ("精選紅茶(中)", True),
        ("精選紅茶(大)", True),
        ("十穀漿(中)", True),
        ("十穀漿(大)", True),
        ("黑糖鮮奶(中)", True),
        ("黑糖鮮奶(大)", True),
    )
    reply = _build_category_reply("飲品", items)

    assert reply == "飲品有5種，像是有糖豆漿、無糖豆漿、精選紅茶，要聽別的嗎？"


def test_few_items_listed_in_full():
    """品項少（蔥抓餅 2 種）直接列全部，報數量反而少講資訊"""
    items = _items(("蔥抓餅(原味)", True), ("蔥抓餅(加蛋)", True))
    reply = _build_category_reply("蔥抓餅", items)

    assert reply == "我們的蔥抓餅有：蔥抓餅(原味)、蔥抓餅(加蛋)，要點哪個？"


def test_sold_out_items_excluded():
    """售完品項不列進代表、也不計入數量"""
    items = _items(
        ("鮮肉包", False),
        ("蔬菜包", True),
        ("豆沙包", True),
        ("白饅頭", True),
        ("黑糖饅頭", True),
        ("芋頭饅頭", True),
    )
    reply = _build_category_reply("饅頭", items)

    assert "鮮肉包" not in reply
    assert reply == "饅頭有5種，像是蔬菜包、豆沙包、白饅頭，要聽別的嗎？"


def test_all_sold_out():
    """整個分類賣完 → 明講賣完，不回空清單"""
    items = _items(("鮮肉包", False), ("蔬菜包", False))
    reply = _build_category_reply("饅頭", items)

    assert reply == "抱歉，饅頭今天都賣完了，要不要看看別的？"
