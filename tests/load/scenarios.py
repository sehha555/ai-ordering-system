"""壓力測試場景定義"""

# 文字點餐場景：模擬完整點餐流程
TEXT_SCENARIOS: list[list[str]] = [
    [
        "我要一個原味飯糰",
        "大杯紅茶",
        "再加一個鐵板麵",
        "結帳",
        "外帶，現金",
    ],
    [
        "有什麼飲料",
        "中杯奶茶去冰",
        "一個蛋餅",
        "結帳",
        "內用",
    ],
    [
        "套餐一",
        "紅茶",
        "結帳",
        "外帶，Line Pay",
    ],
]


def get_text_scenario(index: int) -> list[str]:
    """循環取得文字場景"""
    return TEXT_SCENARIOS[index % len(TEXT_SCENARIOS)]
