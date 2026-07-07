# tests/dm/test_cart_display_customization.py
# 客製顯示：format_item 必須帶出 customization（K — 「蛋餅加辣」資料有存但顯示全丟）
# 顯示鏈單一出口：cart 摘要、結帳確認句、廚房 items_display 都走 format_item

from src.dm import cart_manager


def _egg_pancake(customization=None):
    item = {"itemtype": "egg_pancake", "flavor": "起司", "quantity": 1}
    if customization:
        item["customization"] = customization
    return item


class TestFormatItemCustomization:
    def test_egg_pancake_spicy_shown(self):
        assert cart_manager.format_item(_egg_pancake("加辣")) == "起司蛋餅(加辣)"

    def test_no_customization_unchanged(self):
        assert cart_manager.format_item(_egg_pancake()) == "起司蛋餅"

    def test_carrier_customization_shown(self):
        item = {
            "itemtype": "carrier",
            "menu_name": "培根蛋漢堡",
            "quantity": 1,
            "customization": "不要小黃瓜",
        }
        assert cart_manager.format_item(item) == "培根蛋漢堡(不要小黃瓜)"

    def test_drink_customization_merged_into_details(self):
        # 飲料已有 (大杯, 冰) 細節括號 → 客製併入同一組，不出現雙括號
        item = {
            "itemtype": "drink",
            "drink": "純鮮奶茶",
            "size": "大杯",
            "temp": "冰",
            "customization": "半糖",
        }
        assert cart_manager.format_item(item) == "純鮮奶茶(大杯, 冰, 半糖)"

    def test_riceball_customization_shown(self):
        item = {
            "itemtype": "riceball",
            "rice": "紫米",
            "flavor": "鮪魚飯糰",
            "customization": "加辣菜脯",
        }
        assert cart_manager.format_item(item) == "紫米·鮪魚飯糰(加辣菜脯)"


class TestSummaryCustomization:
    def test_short_summary_includes_customization(self):
        # 結帳確認句用 get_short_summary，客製必須讓客人聽得到
        cart = [_egg_pancake("加辣")]
        assert "加辣" in cart_manager.get_short_summary(cart)

    def test_different_customizations_not_merged(self):
        # 同品項不同客製是兩筆不同的餐，顯示不可合併成 x2
        cart = [_egg_pancake("加辣"), _egg_pancake()]
        summary = cart_manager.get_short_summary(cart)
        assert "起司蛋餅(加辣)、起司蛋餅" == summary
