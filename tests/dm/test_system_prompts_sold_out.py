"""
system_prompts.py 售完資訊注入測試

測試涵蓋：
  - 零售完不注入（不佔 token）
  - 有售完品項時注入正確格式
  - 售完分類注入
  - 套餐連動注入
  - 饅頭選項限制注入
  - 鐵板麵麵種選項限制注入
  - 注入區塊在 system prompt 尾段
"""

import pytest

from src.tools.menu import menu_state_service
from src.dm.system_prompts import SystemPromptBuilder, _get_available_mantou, _format_rice_restriction


# ── Fixture ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """
    每個測試前：
    1. 將 _STATE_FILE 指向 tmp_path（隔離測試環境）
    2. 清除快取
    3. 測試結束後再清快取
    """
    test_state_file = str(tmp_path / "menu_state.json")
    monkeypatch.setattr(menu_state_service, "_STATE_FILE", test_state_file)
    menu_state_service.clear_cache()
    yield
    menu_state_service.clear_cache()


@pytest.fixture
def builder():
    """回傳一個新的 SystemPromptBuilder，base prompt 用 mock 替換"""
    b = SystemPromptBuilder()
    # mock _load_base_prompt 和 _generate_menu_summary 避免讀檔
    b._base_prompt = "# 測試基礎提示"
    b._menu_summary = "# 菜單類別\n- 飯糰：5 項"
    return b


# ── _format_rice_restriction 輔助函式測試 ─────────────────────────────────

class TestFormatRiceRestriction:
    def test_全部可用_回傳空字串(self):
        status = {"purple": True, "white": True, "mixed": True}
        assert _format_rice_restriction(status) == ""

    def test_紫米不可用_混米連帶不可用(self):
        status = {"purple": False, "white": True, "mixed": False}
        result = _format_rice_restriction(status)
        assert "飯糰米種：" in result
        assert "紫米" in result
        assert "混米" in result
        assert "白米" in result  # 白米仍可用，應出現在「可用」部分

    def test_白米不可用_混米連帶不可用(self):
        status = {"purple": True, "white": False, "mixed": False}
        result = _format_rice_restriction(status)
        assert "飯糰米種：" in result
        assert "白米" in result
        assert "混米" in result

    def test_全部不可用(self):
        status = {"purple": False, "white": False, "mixed": False}
        result = _format_rice_restriction(status)
        assert "飯糰米種：" in result
        assert "均不可選" in result


# ── _get_available_mantou 輔助函式測試 ────────────────────────────────────

class TestGetAvailableMantou:
    def test_全部可選_回傳None(self):
        sold_cats = {
            "mantou_black_sugar": False,
            "mantou_white": False,
            "mantou_black_sugar_roll": False,
            "mantou_white_roll": False,
            "mantou_taro": False,
        }
        assert _get_available_mantou(sold_cats) is None

    def test_部分售完_回傳剩餘可選清單(self):
        sold_cats = {
            "mantou_black_sugar": True,   # 黑糖饅頭售完
            "mantou_white": False,
            "mantou_black_sugar_roll": True,  # 黑糖花捲售完
            "mantou_white_roll": False,
            "mantou_taro": False,
        }
        result = _get_available_mantou(sold_cats)
        assert result is not None
        assert "白饅頭" in result
        assert "白花捲" in result
        assert "芋頭饅頭" in result
        assert "黑糖饅頭" not in result
        assert "黑糖花捲" not in result

    def test_全部售完_回傳空清單(self):
        sold_cats = {
            "mantou_black_sugar": True,
            "mantou_white": True,
            "mantou_black_sugar_roll": True,
            "mantou_white_roll": True,
            "mantou_taro": True,
        }
        result = _get_available_mantou(sold_cats)
        assert result == []


# ── _format_sold_out_info 核心測試 ─────────────────────────────────────────

class TestFormatSoldOutInfo:
    def test_零售完_回傳空字串(self, builder):
        """全部正常時不產生任何內容，不佔 token"""
        result = builder._format_sold_out_info()
        assert result == ""

    def test_有售完品項_注入格式正確(self, builder):
        """品項級售完 → 出現「售完品項：」行"""
        menu_state_service.set_item_sold_out("甜飯糰", True)
        result = builder._format_sold_out_info()
        assert "【售完資訊】" in result
        assert "售完品項：" in result
        assert "甜飯糰" in result
        assert "顧客點售完品項時，請告知已售完。" in result

    def test_有售完分類_注入售完分類行(self, builder):
        """分類級售完（吐司）→ 出現「售完分類：」行"""
        menu_state_service.set_category_sold_out("carrier_toast", True)
        result = builder._format_sold_out_info()
        assert "【售完資訊】" in result
        assert "售完分類：" in result
        assert "吐司" in result

    def test_套餐連動_注入不可用套餐(self, builder):
        """吐司分類售完 → 套餐A、D、兒童餐不可用"""
        menu_state_service.set_category_sold_out("carrier_toast", True)
        result = builder._format_sold_out_info()
        assert "不可用套餐：" in result
        assert "套餐A" in result
        assert "套餐D" in result
        assert "兒童餐" in result

    def test_饅頭部分售完_注入選項限制(self, builder):
        """部分饅頭售完 → 出現饅頭選項限制"""
        menu_state_service.set_category_sold_out("mantou_black_sugar", True)
        menu_state_service.set_category_sold_out("mantou_taro", True)
        result = builder._format_sold_out_info()
        assert "選項限制：" in result
        assert "饅頭目前只有" in result
        # 剩餘可選的饅頭應出現
        assert "白饅頭" in result
        assert "白花捲" in result
        assert "黑糖花捲" in result

    def test_饅頭全部售完_不重複列選項限制(self, builder):
        """饅頭全部售完時，品項由 effective_items 呈現，不另列選項限制"""
        for key in ["mantou_black_sugar", "mantou_white", "mantou_black_sugar_roll",
                    "mantou_white_roll", "mantou_taro"]:
            menu_state_service.set_category_sold_out(key, True)
        result = builder._format_sold_out_info()
        # 不應有「選項限制：饅頭」行（空 list 情況不注入選項限制）
        assert "饅頭目前只有" not in result

    def test_只有油麵售完_注入只能選烏龍麵(self, builder):
        """油麵售完、烏龍可用 → 選項限制顯示只能選烏龍麵"""
        menu_state_service.set_category_sold_out("noodle_oil", True)
        result = builder._format_sold_out_info()
        assert "選項限制：" in result
        assert "鐵板麵目前只能選烏龍麵" in result

    def test_只有烏龍售完_注入只能選油麵(self, builder):
        """烏龍麵售完、油麵可用 → 選項限制顯示只能選油麵"""
        menu_state_service.set_category_sold_out("noodle_udon", True)
        result = builder._format_sold_out_info()
        assert "選項限制：" in result
        assert "鐵板麵目前只能選油麵" in result

    def test_紫米售完_注入米種選項限制(self, builder):
        """紫米售完 → 顯示紫米不可選且混米不可選"""
        menu_state_service.set_category_sold_out("rice_purple", True)
        result = builder._format_sold_out_info()
        assert "選項限制：" in result
        assert "飯糰米種：" in result
        assert "紫米" in result

    def test_白米售完_注入米種選項限制(self, builder):
        """白米售完 → 顯示白米不可選且混米不可選"""
        menu_state_service.set_category_sold_out("rice_white", True)
        result = builder._format_sold_out_info()
        assert "選項限制：" in result
        assert "飯糰米種：" in result
        assert "白米" in result

    def test_紫米白米都售完_注入全部米種不可選(self, builder):
        """紫米和白米都售完 → 三種米全不可選"""
        menu_state_service.set_category_sold_out("rice_purple", True)
        menu_state_service.set_category_sold_out("rice_white", True)
        result = builder._format_sold_out_info()
        assert "選項限制：" in result
        assert "飯糰米種：" in result

    def test_米種全部可用_不注入選項限制(self, builder):
        """米種全部可用時不應出現飯糰米種限制"""
        result = builder._format_sold_out_info()
        assert "飯糰米種：" not in result

    def test_油麵烏龍都售完_不列麵種選項限制(self, builder):
        """兩種麵都售完 → 鐵板麵品項會在 effective_items 中，不另列選項限制"""
        menu_state_service.set_category_sold_out("noodle_oil", True)
        menu_state_service.set_category_sold_out("noodle_udon", True)
        result = builder._format_sold_out_info()
        # 不應出現「鐵板麵目前只能選」行
        assert "鐵板麵目前只能選" not in result

    def test_多種售完同時注入(self, builder):
        """品項售完 + 分類售完 + 套餐不可用 同時出現"""
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.set_category_sold_out("carrier_toast", True)
        result = builder._format_sold_out_info()
        assert "售完品項：" in result
        assert "售完分類：" in result
        assert "不可用套餐：" in result


# ── build() 整合測試 ────────────────────────────────────────────────────────

class TestBuildWithSoldOut:
    def test_零售完_build結果不含售完區塊(self, builder):
        """全部正常時 build() 輸出不含售完資訊"""
        result = builder.build()
        assert "【售完資訊】" not in result

    def test_有售完_build結果含售完區塊(self, builder):
        """有售完品項時 build() 輸出末尾含售完資訊"""
        menu_state_service.set_item_sold_out("甜飯糰", True)
        result = builder.build()
        assert "【售完資訊】" in result

    def test_售完資訊在尾段_靜態內容在前(self, builder):
        """確認售完資訊放在所有靜態內容之後"""
        menu_state_service.set_item_sold_out("甜飯糰", True)
        result = builder.build()
        sold_out_pos = result.index("【售完資訊】")
        base_prompt_pos = result.index("# 測試基礎提示")
        menu_summary_pos = result.index("# 菜單類別")
        # 售完資訊必須在基礎提示和菜單摘要之後
        assert sold_out_pos > base_prompt_pos
        assert sold_out_pos > menu_summary_pos

    def test_售完資訊包含結尾提示語(self, builder):
        """確認結尾「請告知已售完」提示語存在"""
        menu_state_service.set_item_sold_out("甜飯糰", True)
        result = builder.build()
        assert "顧客點售完品項時，請告知已售完。" in result
