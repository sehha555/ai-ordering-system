"""
menu_state_service 單元測試

測試涵蓋：
  - 基本讀寫（品項、分類、營業時間）
  - 連動規則引擎（get_effective_sold_out）
  - 套餐狀態計算（get_effective_combo_status）
  - is_currently_open 邏輯
"""

import json
import os
import pytest
from unittest.mock import patch
from datetime import datetime

from src.tools.menu import menu_state_service


# ── Fixture ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """
    每個測試前：
    1. 清除模組快取
    2. 將 _STATE_FILE 指向 tmp_path/menu_state.json（隔離測試環境）
    3. 測試結束後再清快取
    """
    test_state_file = str(tmp_path / "menu_state.json")
    monkeypatch.setattr(menu_state_service, "_STATE_FILE", test_state_file)
    menu_state_service.clear_cache()
    yield
    menu_state_service.clear_cache()


# ── 基本讀寫 ──────────────────────────────────────────────────────────────

class TestGetState:
    def test_回傳預設狀態_當檔案不存在(self):
        state = menu_state_service.get_state()
        assert state["sold_out_items"] == []
        assert state["is_open_override"] is None
        assert state["business_hours"]["open"] == "06:00"

    def test_所有分類預設為false(self):
        cats = menu_state_service.get_sold_out_categories()
        for key, val in cats.items():
            assert val is False, f"{key} 預設應為 False"


class TestSetItemSoldOut:
    def test_設定品項售完(self):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        items = menu_state_service.get_sold_out_items()
        assert "甜飯糰" in items

    def test_恢復品項(self):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.set_item_sold_out("甜飯糰", False)
        items = menu_state_service.get_sold_out_items()
        assert "甜飯糰" not in items

    def test_重複設定售完不重複加入(self):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.set_item_sold_out("甜飯糰", True)
        items = menu_state_service.get_sold_out_items()
        assert items.count("甜飯糰") == 1

    def test_恢復不存在品項不報錯(self):
        # 不應拋出例外
        menu_state_service.set_item_sold_out("不存在的品項", False)


class TestSetCategorySoldOut:
    def test_設定合法分類(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        cats = menu_state_service.get_sold_out_categories()
        assert cats["carrier_toast"] is True

    def test_設定不合法分類拋出KeyError(self):
        with pytest.raises(KeyError):
            menu_state_service.set_category_sold_out("不存在的key", True)


class TestResetAllSoldOut:
    def test_一鍵恢復清空品項和分類(self):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.set_category_sold_out("carrier_toast", True)
        menu_state_service.reset_all_sold_out()
        assert menu_state_service.get_sold_out_items() == []
        cats = menu_state_service.get_sold_out_categories()
        assert all(v is False for v in cats.values())


# ── 連動規則：get_effective_sold_out ──────────────────────────────────────

class TestEffectiveSoldOut:
    # 規則1：載體
    def test_吐司關_連動所有吐司品項(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "煎蛋吐司" in sold
        assert "起司蛋吐司" in sold
        assert "醬燒肉片總匯吐司" in sold

    def test_吐司關_連動薄片果醬吐司(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "果醬吐司(草莓/薄片)" in sold
        assert "果醬吐司(花生/薄片)" in sold

    def test_吐司關_不影響厚片果醬吐司(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "果醬吐司(草莓/厚片)" not in sold

    def test_厚片關_連動厚片果醬吐司(self):
        menu_state_service.set_category_sold_out("carrier_thick_toast", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "果醬吐司(草莓/厚片)" in sold
        assert "果醬吐司(奶酥/厚片)" in sold

    def test_厚片關_不影響薄片(self):
        menu_state_service.set_category_sold_out("carrier_thick_toast", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "果醬吐司(草莓/薄片)" not in sold

    def test_漢堡關_連動所有漢堡品項(self):
        menu_state_service.set_category_sold_out("carrier_burger", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "火腿蛋漢堡" in sold
        assert "原味咔啦雞蛋漢堡" in sold

    # 規則2：米種（米種是點餐選項，不是獨立品項，不會加入 effective_sold_out）
    # 米種狀態改由 get_rice_options_status() 回傳，供 system_prompts 注入選項限制
    def test_紫米關_不加假品項名到售完清單(self):
        menu_state_service.set_category_sold_out("rice_purple", True)
        sold = menu_state_service.get_effective_sold_out()
        # 「紫米飯糰」不是真實品項，不應出現在售完清單
        assert "紫米飯糰" not in sold
        assert "混米飯糰" not in sold

    def test_白米關_不加假品項名到售完清單(self):
        menu_state_service.set_category_sold_out("rice_white", True)
        sold = menu_state_service.get_effective_sold_out()
        # 「白米飯糰」不是真實品項，不應出現在售完清單
        assert "白米飯糰" not in sold
        assert "混米飯糰" not in sold

    def test_白米和紫米都未關_售完清單無米種假品項(self):
        sold = menu_state_service.get_effective_sold_out()
        assert "紫米飯糰" not in sold
        assert "白米飯糰" not in sold
        assert "混米飯糰" not in sold


# ── get_rice_options_status 米種選項狀態測試 ──────────────────────────────

class TestGetRiceOptionsStatus:
    def test_預設全部米種可用(self):
        status = menu_state_service.get_rice_options_status()
        assert status["purple"] is True
        assert status["white"] is True
        assert status["mixed"] is True

    def test_紫米關_紫米不可用_混米也不可用(self):
        menu_state_service.set_category_sold_out("rice_purple", True)
        status = menu_state_service.get_rice_options_status()
        assert status["purple"] is False
        assert status["white"] is True
        assert status["mixed"] is False  # 混米需要紫米和白米都有

    def test_白米關_白米不可用_混米也不可用(self):
        menu_state_service.set_category_sold_out("rice_white", True)
        status = menu_state_service.get_rice_options_status()
        assert status["purple"] is True
        assert status["white"] is False
        assert status["mixed"] is False  # 混米需要紫米和白米都有

    def test_紫米白米都關_三種米全不可用(self):
        menu_state_service.set_category_sold_out("rice_purple", True)
        menu_state_service.set_category_sold_out("rice_white", True)
        status = menu_state_service.get_rice_options_status()
        assert status["purple"] is False
        assert status["white"] is False
        assert status["mixed"] is False

    # 規則3：饅頭
    def test_黑糖饅頭分類關_對應品項關(self):
        menu_state_service.set_category_sold_out("mantou_black_sugar", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "黑糖饅頭" in sold

    def test_白花捲分類關_對應品項關(self):
        menu_state_service.set_category_sold_out("mantou_white_roll", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "白花捲" in sold

    def test_芋頭饅頭分類關_對應品項關(self):
        menu_state_service.set_category_sold_out("mantou_taro", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "芋頭饅頭" in sold

    def test_饅頭分類各自獨立_不互相影響(self):
        menu_state_service.set_category_sold_out("mantou_black_sugar", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "白饅頭" not in sold
        assert "黑糖花捲" not in sold

    # 規則4：鐵板麵麵種
    def test_烏龍關_咖哩烏龍直接關(self):
        menu_state_service.set_category_sold_out("noodle_udon", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "咖哩烏龍麵+蛋" in sold

    def test_只有油麵關_不影響咖哩烏龍(self):
        menu_state_service.set_category_sold_out("noodle_oil", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "咖哩烏龍麵+蛋" not in sold

    def test_油麵和烏龍都關_黑椒蘑菇義大利也關(self):
        menu_state_service.set_category_sold_out("noodle_udon", True)
        menu_state_service.set_category_sold_out("noodle_oil", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "黑椒鐵板麵+蛋" in sold
        assert "蘑菇鐵板麵+蛋" in sold
        assert "義大利肉醬麵+蛋" in sold
        assert "咖哩烏龍麵+蛋" in sold

    def test_只有烏龍關_黑椒蘑菇義大利不關(self):
        menu_state_service.set_category_sold_out("noodle_udon", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "黑椒鐵板麵+蛋" not in sold
        assert "蘑菇鐵板麵+蛋" not in sold

    # 規則5：蔥抓餅
    def test_蔥抓餅分類關_原味和加蛋都關(self):
        menu_state_service.set_category_sold_out("scallion_pancake", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "蔥抓餅(原味)" in sold
        assert "蔥抓餅(加蛋)" in sold

    # 品項級和分類級同時存在
    def test_品項售完和分類售完合併(self):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.set_category_sold_out("carrier_toast", True)
        sold = menu_state_service.get_effective_sold_out()
        assert "甜飯糰" in sold
        assert "煎蛋吐司" in sold

    def test_全部未設定_回傳空清單(self):
        sold = menu_state_service.get_effective_sold_out()
        assert sold == []


# ── 套餐連動：get_effective_combo_status ─────────────────────────────────

class TestEffectiveComboStatus:
    def test_初始狀態全部套餐可用(self):
        combos = menu_state_service.get_effective_combo_status()
        for name, status in combos.items():
            assert status["available"] is True, f"{name} 初始應為可用"
            assert status["reason"] is None

    def test_醬燒肉片蛋餅售完_套餐一關閉(self):
        menu_state_service.set_item_sold_out("醬燒肉片蛋餅", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐一"]["available"] is False
        assert "醬燒肉片蛋餅" in combos["套餐一"]["reason"]

    def test_紫米白米都關_套餐二關閉(self):
        menu_state_service.set_category_sold_out("rice_purple", True)
        menu_state_service.set_category_sold_out("rice_white", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐二"]["available"] is False

    def test_只有紫米關_套餐二仍可用(self):
        menu_state_service.set_category_sold_out("rice_purple", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐二"]["available"] is True

    def test_高麗菜蛋餅售完_套餐三關閉(self):
        menu_state_service.set_item_sold_out("高麗菜蛋餅", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐三"]["available"] is False

    def test_港式蘿蔔糕售完_套餐四關閉(self):
        menu_state_service.set_item_sold_out("港式蘿蔔糕", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐四"]["available"] is False

    def test_5種饅頭全關_套餐五關閉(self):
        for key in ["mantou_black_sugar", "mantou_white", "mantou_black_sugar_roll",
                    "mantou_white_roll", "mantou_taro"]:
            menu_state_service.set_category_sold_out(key, True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐五"]["available"] is False

    def test_只有4種饅頭關_套餐五仍可用(self):
        for key in ["mantou_black_sugar", "mantou_white", "mantou_black_sugar_roll",
                    "mantou_white_roll"]:
            menu_state_service.set_category_sold_out(key, True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐五"]["available"] is True

    def test_饅頭品項級售完也計入套餐五判斷(self):
        # 4 種用分類關，1 種用品項級售完
        for key in ["mantou_black_sugar", "mantou_white", "mantou_black_sugar_roll",
                    "mantou_white_roll"]:
            menu_state_service.set_category_sold_out(key, True)
        menu_state_service.set_item_sold_out("芋頭饅頭", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐五"]["available"] is False

    def test_油麵烏龍都關_套餐六七C同時關閉(self):
        menu_state_service.set_category_sold_out("noodle_udon", True)
        menu_state_service.set_category_sold_out("noodle_oil", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐六"]["available"] is False
        assert combos["套餐七"]["available"] is False
        assert combos["套餐C"]["available"] is False

    def test_只有烏龍關_套餐六七C仍可用(self):
        menu_state_service.set_category_sold_out("noodle_udon", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐六"]["available"] is True

    def test_無骨雞排售完_套餐七和E關閉(self):
        menu_state_service.set_item_sold_out("無骨雞排", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐七"]["available"] is False
        assert combos["套餐E"]["available"] is False

    def test_套餐七_複合原因(self):
        menu_state_service.set_category_sold_out("noodle_udon", True)
        menu_state_service.set_category_sold_out("noodle_oil", True)
        menu_state_service.set_item_sold_out("無骨雞排", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐七"]["available"] is False
        # reason 應包含兩個原因
        assert "油麵" in combos["套餐七"]["reason"]
        assert "無骨雞排" in combos["套餐七"]["reason"]

    def test_吐司關_套餐ABD兒童餐關閉(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐A"]["available"] is False
        assert combos["套餐D"]["available"] is False
        assert combos["兒童餐"]["available"] is False

    def test_吐司關_不影響套餐B(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐B"]["available"] is True

    def test_厚片關_只關套餐B(self):
        menu_state_service.set_category_sold_out("carrier_thick_toast", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐B"]["available"] is False
        assert combos["套餐A"]["available"] is True

    def test_漢堡關_只關套餐E(self):
        menu_state_service.set_category_sold_out("carrier_burger", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐E"]["available"] is False
        assert combos["套餐A"]["available"] is True

    def test_套餐E_複合原因(self):
        menu_state_service.set_category_sold_out("carrier_burger", True)
        menu_state_service.set_item_sold_out("無骨雞排", True)
        combos = menu_state_service.get_effective_combo_status()
        assert combos["套餐E"]["available"] is False
        assert "漢堡" in combos["套餐E"]["reason"]
        assert "無骨雞排" in combos["套餐E"]["reason"]


# ── 營業時間 ──────────────────────────────────────────────────────────────

class TestBusinessHours:
    def test_取得預設營業時間(self):
        hours = menu_state_service.get_business_hours()
        assert hours["open"] == "06:00"
        assert hours["close"] == "14:00"

    def test_設定營業時間(self):
        menu_state_service.set_business_hours("07:30", "15:00")
        hours = menu_state_service.get_business_hours()
        assert hours["open"] == "07:30"
        assert hours["close"] == "15:00"


class TestIsCurrentlyOpen:
    def test_強制開啟_is_open_override_true(self):
        menu_state_service.set_open_override(True)
        assert menu_state_service.is_currently_open() is True

    def test_強制關閉_is_open_override_false(self):
        menu_state_service.set_open_override(False)
        assert menu_state_service.is_currently_open() is False

    def test_override重設為None_回到自動模式(self):
        menu_state_service.set_open_override(True)
        menu_state_service.set_open_override(None)
        # 回到自動模式，不強制斷言結果（依當前時間）
        result = menu_state_service.is_currently_open()
        assert isinstance(result, bool)

    def test_自動模式_營業時間內(self):
        menu_state_service.set_business_hours("00:00", "23:59")
        assert menu_state_service.is_currently_open() is True

    def test_自動模式_非營業時間(self):
        menu_state_service.set_business_hours("00:00", "00:01")
        # 除非現在是 00:00，否則應為 False
        now = datetime.now().strftime("%H:%M")
        if now >= "00:01":
            assert menu_state_service.is_currently_open() is False


class TestSetOpenOverride:
    def test_設定true(self):
        menu_state_service.set_open_override(True)
        state = menu_state_service.get_state()
        assert state["is_open_override"] is True

    def test_設定false(self):
        menu_state_service.set_open_override(False)
        state = menu_state_service.get_state()
        assert state["is_open_override"] is False

    def test_設定none(self):
        menu_state_service.set_open_override(True)
        menu_state_service.set_open_override(None)
        state = menu_state_service.get_state()
        assert state["is_open_override"] is None


# ── 持久化驗證 ────────────────────────────────────────────────────────────

class TestPersistence:
    def test_狀態寫入後重載快取仍保留(self):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.clear_cache()
        items = menu_state_service.get_sold_out_items()
        assert "甜飯糰" in items

    def test_分類狀態持久化(self):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        menu_state_service.clear_cache()
        cats = menu_state_service.get_sold_out_categories()
        assert cats["carrier_toast"] is True
