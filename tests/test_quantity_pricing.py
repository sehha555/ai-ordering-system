"""
驗收測試：飯糰與 carrier 品項 quantity > 1 時計價正確。
回歸 quantity=1 行為不變。
"""

import pytest
from src.dm.cart_manager import get_price_info, calculate_cart_total
from src.tools.riceball_tool import menu_tool
from src.tools.carrier_tool import carrier_tool
from src.tools.menu import menu_price_service


@pytest.fixture(autouse=True)
def clear_menu_cache():
    menu_price_service.clear_cache()
    yield
    menu_price_service.clear_cache()


# ---------- 輔助 ----------


def _riceball_item(flavor="源味傳統", rice="紫米", quantity=1, **kw):
    item = {"itemtype": "riceball", "flavor": flavor, "rice": rice, "quantity": quantity}
    item.update(kw)
    return item


def _carrier_item(carrier="吐司", flavor="火腿蛋", quantity=1, menu_name=None, **kw):
    item = {
        "itemtype": "carrier",
        "carrier": carrier,
        "flavor": flavor,
        "quantity": quantity,
        "ingredients_add": [],
    }
    if menu_name:
        item["menu_name"] = menu_name
    item.update(kw)
    return item


def _single_riceball_price(flavor="源味傳統", **kw):
    """取得單顆飯糰單價（不含 addon）"""
    pi = menu_tool.quote_riceball_price(flavor=flavor, quantity=1, **kw)
    assert pi["ok"]
    return pi["single_price"]


def _single_carrier_price(carrier="吐司", flavor="火腿蛋"):
    """取得單份 carrier 單價"""
    frame = _carrier_item(carrier=carrier, flavor=flavor, quantity=1)
    pi = carrier_tool.quote_carrier_price(frame)
    assert pi["ok"]
    return pi["single_price"]


# ---------- 飯糰測試 ----------


def test_riceball_qty1_unchanged():
    """quantity=1 回傳值與未改前一致（single_price == total_price）"""
    pi = menu_tool.quote_riceball_price(flavor="源味傳統", quantity=1)
    assert pi["ok"]
    assert pi["total_price"] == pi["single_price"]
    assert pi["quantity"] == 1


def test_riceball_qty3_total():
    """quantity=3 → total_price = 3 × single_price"""
    single = _single_riceball_price()
    pi = menu_tool.quote_riceball_price(flavor="源味傳統", quantity=3)
    assert pi["ok"]
    assert pi["total_price"] == single * 3
    assert pi["single_price"] == single
    assert pi["quantity"] == 3


def test_riceball_qty3_via_get_price_info():
    """cart entry quantity=3 → get_price_info 回傳含數量的 total_price"""
    single = _single_riceball_price()
    item = _riceball_item(quantity=3)
    pi = get_price_info(item)
    assert pi["ok"]
    assert pi["total_price"] == single * 3


def test_riceball_qty3_with_addon():
    """quantity=3，有加料（加起司+10）→ total = 3 × (base + 10)"""
    single = _single_riceball_price()
    item = _riceball_item(quantity=3, customization="加起司")
    pi = get_price_info(item)
    assert pi["ok"]
    expected = (single + 10) * 3
    assert pi["total_price"] == expected


def test_riceball_large_qty2():
    """加大+5 × 2顆 → 正確加倍"""
    single_large = _single_riceball_price(large=True)
    item = _riceball_item(quantity=2, large=True)
    pi = get_price_info(item)
    assert pi["ok"]
    assert pi["total_price"] == single_large * 2


def test_riceball_cart_total_qty3():
    """calculate_cart_total：飯糰 qty=3 加入購物車，總價正確"""
    single = _single_riceball_price()
    cart = [_riceball_item(quantity=3)]
    total = calculate_cart_total(cart)
    assert total == single * 3


# ---------- carrier 測試 ----------


def test_carrier_qty1_unchanged():
    """quantity=1 時 single_price == total_price"""
    pi = carrier_tool.quote_carrier_price(_carrier_item(quantity=1))
    assert pi["ok"]
    assert pi["total_price"] == pi["single_price"]
    assert pi["quantity"] == 1


def test_carrier_qty2_total():
    """quantity=2 → total_price = 2 × single_price"""
    single = _single_carrier_price()
    frame = _carrier_item(quantity=2)
    pi = carrier_tool.quote_carrier_price(frame)
    assert pi["ok"]
    assert pi["total_price"] == single * 2
    assert pi["quantity"] == 2


def test_carrier_qty2_via_get_price_info():
    """cart entry quantity=2 → get_price_info 回傳含數量的 total_price"""
    single = _single_carrier_price()
    item = _carrier_item(quantity=2)
    pi = get_price_info(item)
    assert pi["ok"]
    assert pi["total_price"] == single * 2


def test_carrier_cart_total_qty2():
    """calculate_cart_total：carrier qty=2，總價正確"""
    single = _single_carrier_price()
    cart = [_carrier_item(quantity=2)]
    total = calculate_cart_total(cart)
    assert total == single * 2


def test_carrier_with_addon_qty2():
    """carrier 有加料 qty=2 → total = 2 × (base + addon)"""
    # 先取得無加料的單價
    pi_no_addon = carrier_tool.quote_carrier_price(_carrier_item(quantity=1))
    assert pi_no_addon["ok"]
    base = pi_no_addon["single_price"]

    # 加起司：需確認 ADDON_PRICE_TABLE 有「起司」，否則 skip
    from src.tools.riceball_tool import menu_tool as rt

    addon_price = rt.ADDON_PRICE_TABLE.get("起司")
    if addon_price is None:
        pytest.skip("起司不在加料表")

    item = _carrier_item(quantity=2, ingredients_add=["起司"])
    pi = get_price_info(item)
    assert pi["ok"]
    expected = (base + addon_price) * 2
    assert pi["total_price"] == expected
