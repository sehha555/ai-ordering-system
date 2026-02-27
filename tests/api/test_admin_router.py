"""
Admin Router API 測試

測試涵蓋所有 /admin/* 端點：
- GET  /admin/menu/state
- PUT  /admin/menu/sold-out/item
- PUT  /admin/menu/sold-out/category
- POST /admin/menu/reset-sold-out
- PUT  /admin/menu/business-hours
- PUT  /admin/menu/open-override
"""

import pytest
from fastapi.testclient import TestClient

from src.tools.menu import menu_state_service


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_menu_state(tmp_path, monkeypatch):
    """
    每個測試前：
    - 將 _STATE_FILE 指向獨立的 tmp_path（避免污染真實 menu_state.json）
    - 清除快取
    測試後再清快取
    """
    test_state_file = str(tmp_path / "menu_state.json")
    monkeypatch.setattr(menu_state_service, "_STATE_FILE", test_state_file)
    menu_state_service.clear_cache()
    yield
    menu_state_service.clear_cache()


@pytest.fixture
def client():
    """建立 TestClient，使用 app 的 lifespan 以外的輕量版本。"""
    from src.api.app import app
    # 使用 raise_server_exceptions=True 確保錯誤會拋出
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── GET /admin/menu/state ─────────────────────────────────────────────────

class TestGetMenuState:
    def test_回傳預設狀態結構(self, client):
        """回應必須包含所有必要欄位，包含 categories"""
        r = client.get("/admin/menu/state")
        assert r.status_code == 200
        data = r.json()
        assert "sold_out_items" in data
        assert "sold_out_categories" in data
        assert "effective_sold_out" in data
        assert "combo_status" in data
        assert "business_hours" in data
        assert "is_currently_open" in data
        assert "is_open_override" in data
        assert "categories" in data

    def test_categories包含分類列表(self, client):
        """categories 欄位格式：[{name, icon, items: [{name, price}]}]"""
        r = client.get("/admin/menu/state")
        data = r.json()
        categories = data["categories"]
        assert isinstance(categories, list)
        assert len(categories) > 0
        # 驗證每個分類都有 name、icon、items 欄位
        for cat in categories:
            assert "name" in cat
            assert "icon" in cat
            assert "items" in cat
            assert isinstance(cat["items"], list)

    def test_categories包含飯糰分類(self, client):
        """菜單必須包含飯糰分類"""
        r = client.get("/admin/menu/state")
        categories = r.json()["categories"]
        cat_names = [c["name"] for c in categories]
        assert "飯糰" in cat_names

    def test_categories品項格式正確(self, client):
        """分類下的品項需有 name 和 price 欄位"""
        r = client.get("/admin/menu/state")
        categories = r.json()["categories"]
        # 取第一個分類的第一個品項驗證格式
        first_cat = categories[0]
        assert len(first_cat["items"]) > 0
        first_item = first_cat["items"][0]
        assert "name" in first_item
        assert "price" in first_item
        assert isinstance(first_item["price"], int)

    def test_預設售完清單為空(self, client):
        r = client.get("/admin/menu/state")
        data = r.json()
        assert data["sold_out_items"] == []
        assert data["effective_sold_out"] == []

    def test_預設is_open_override為null(self, client):
        r = client.get("/admin/menu/state")
        data = r.json()
        assert data["is_open_override"] is None

    def test_預設營業時間(self, client):
        r = client.get("/admin/menu/state")
        data = r.json()
        assert data["business_hours"]["open"] == "06:00"
        assert data["business_hours"]["close"] == "14:00"

    def test_所有分類預設為false(self, client):
        r = client.get("/admin/menu/state")
        cats = r.json()["sold_out_categories"]
        assert len(cats) > 0
        for key, val in cats.items():
            assert val is False, f"{key} 預設應為 False"

    def test_combo_status包含所有套餐(self, client):
        r = client.get("/admin/menu/state")
        combos = r.json()["combo_status"]
        assert "套餐一" in combos
        assert "套餐E" in combos
        assert "兒童餐" in combos

    def test_設定售完後狀態反映(self, client):
        """設定品項售完後，state 端點應反映新狀態"""
        menu_state_service.set_item_sold_out("甜飯糰", True)
        r = client.get("/admin/menu/state")
        data = r.json()
        assert "甜飯糰" in data["sold_out_items"]
        assert "甜飯糰" in data["effective_sold_out"]

    def test_連動規則反映在effective_sold_out(self, client):
        """吐司載體關閉後 effective_sold_out 應包含連動品項"""
        menu_state_service.set_category_sold_out("carrier_toast", True)
        r = client.get("/admin/menu/state")
        data = r.json()
        assert "煎蛋吐司" in data["effective_sold_out"]
        assert "果醬吐司(草莓/薄片)" in data["effective_sold_out"]

    def test_is_currently_open回傳布林值(self, client):
        r = client.get("/admin/menu/state")
        data = r.json()
        assert isinstance(data["is_currently_open"], bool)


# ── PUT /admin/menu/sold-out/item ────────────────────────────────────────

class TestUpdateItemSoldOut:
    def test_設定存在品項為售完(self, client):
        r = client.put("/admin/menu/sold-out/item", json={"name": "甜飯糰", "sold_out": True})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["name"] == "甜飯糰"
        assert data["sold_out"] is True
        # 驗證實際狀態已更新
        assert "甜飯糰" in menu_state_service.get_sold_out_items()

    def test_恢復品項售完(self, client):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        r = client.put("/admin/menu/sold-out/item", json={"name": "甜飯糰", "sold_out": False})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "甜飯糰" not in menu_state_service.get_sold_out_items()

    def test_不存在品項回400(self, client):
        r = client.put("/admin/menu/sold-out/item", json={"name": "不存在的品項ABC", "sold_out": True})
        assert r.status_code == 400
        assert "不存在" in r.json()["detail"]

    def test_設定真實品項名稱(self, client):
        """使用真實菜單品項"""
        r = client.put("/admin/menu/sold-out/item", json={"name": "煎蛋吐司", "sold_out": True})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_空字串品項名回400(self, client):
        r = client.put("/admin/menu/sold-out/item", json={"name": "", "sold_out": True})
        assert r.status_code == 400


# ── PUT /admin/menu/sold-out/category ────────────────────────────────────

class TestUpdateCategorySoldOut:
    def test_設定合法分類售完(self, client):
        r = client.put("/admin/menu/sold-out/category", json={"key": "carrier_toast", "sold_out": True})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["key"] == "carrier_toast"
        assert data["sold_out"] is True
        # 驗證實際狀態
        cats = menu_state_service.get_sold_out_categories()
        assert cats["carrier_toast"] is True

    def test_恢復分類售完(self, client):
        menu_state_service.set_category_sold_out("carrier_toast", True)
        r = client.put("/admin/menu/sold-out/category", json={"key": "carrier_toast", "sold_out": False})
        assert r.status_code == 200
        cats = menu_state_service.get_sold_out_categories()
        assert cats["carrier_toast"] is False

    def test_不合法分類key回400(self, client):
        r = client.put("/admin/menu/sold-out/category", json={"key": "不存在的key", "sold_out": True})
        assert r.status_code == 400

    def test_所有合法key皆可設定(self, client):
        """測試幾個代表性合法 key"""
        valid_keys = ["carrier_toast", "carrier_burger", "rice_purple", "noodle_udon", "scallion_pancake"]
        for key in valid_keys:
            r = client.put("/admin/menu/sold-out/category", json={"key": key, "sold_out": True})
            assert r.status_code == 200, f"{key} 應為合法 key"

    def test_設定rice_purple分類(self, client):
        r = client.put("/admin/menu/sold-out/category", json={"key": "rice_purple", "sold_out": True})
        assert r.status_code == 200
        cats = menu_state_service.get_sold_out_categories()
        assert cats["rice_purple"] is True


# ── POST /admin/menu/reset-sold-out ──────────────────────────────────────

class TestResetSoldOut:
    def test_一鍵恢復清空所有售完(self, client):
        # 先設定一些售完狀態
        menu_state_service.set_item_sold_out("甜飯糰", True)
        menu_state_service.set_category_sold_out("carrier_toast", True)

        r = client.post("/admin/menu/reset-sold-out")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

        # 驗證確實清空
        assert menu_state_service.get_sold_out_items() == []
        cats = menu_state_service.get_sold_out_categories()
        assert all(v is False for v in cats.values())

    def test_空狀態下恢復不報錯(self, client):
        """初始狀態下也能成功呼叫"""
        r = client.post("/admin/menu/reset-sold-out")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_恢復後state端點反映空清單(self, client):
        menu_state_service.set_item_sold_out("甜飯糰", True)
        client.post("/admin/menu/reset-sold-out")
        r = client.get("/admin/menu/state")
        data = r.json()
        assert data["sold_out_items"] == []
        assert data["effective_sold_out"] == []


# ── PUT /admin/menu/business-hours ───────────────────────────────────────

class TestUpdateBusinessHours:
    def test_更新營業時間(self, client):
        r = client.put("/admin/menu/business-hours", json={"open": "07:30", "close": "15:00"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["open"] == "07:30"
        assert data["close"] == "15:00"
        # 驗證實際狀態
        hours = menu_state_service.get_business_hours()
        assert hours["open"] == "07:30"
        assert hours["close"] == "15:00"

    def test_格式正確HH_MM(self, client):
        r = client.put("/admin/menu/business-hours", json={"open": "00:00", "close": "23:59"})
        assert r.status_code == 200

    def test_open格式不合法回400(self, client):
        r = client.put("/admin/menu/business-hours", json={"open": "9:00", "close": "14:00"})
        assert r.status_code == 400

    def test_close格式不合法回400(self, client):
        r = client.put("/admin/menu/business-hours", json={"open": "06:00", "close": "2pm"})
        assert r.status_code == 400

    def test_兩個欄位格式都不合法回400(self, client):
        r = client.put("/admin/menu/business-hours", json={"open": "six", "close": "two"})
        assert r.status_code == 400

    def test_更新後state端點反映新時間(self, client):
        client.put("/admin/menu/business-hours", json={"open": "08:00", "close": "16:00"})
        r = client.get("/admin/menu/state")
        hours = r.json()["business_hours"]
        assert hours["open"] == "08:00"
        assert hours["close"] == "16:00"


# ── PUT /admin/menu/open-override ────────────────────────────────────────

class TestUpdateOpenOverride:
    def test_強制開啟(self, client):
        r = client.put("/admin/menu/open-override", json={"override": True})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["override"] is True
        assert menu_state_service.is_currently_open() is True

    def test_強制關閉(self, client):
        r = client.put("/admin/menu/open-override", json={"override": False})
        assert r.status_code == 200
        assert r.json()["override"] is False
        assert menu_state_service.is_currently_open() is False

    def test_回到自動模式(self, client):
        # 先設定強制開
        client.put("/admin/menu/open-override", json={"override": True})
        # 再回自動
        r = client.put("/admin/menu/open-override", json={"override": None})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["override"] is None
        # 回到自動後 override 應為 None
        state = menu_state_service.get_state()
        assert state["is_open_override"] is None

    def test_override狀態反映在state端點(self, client):
        client.put("/admin/menu/open-override", json={"override": True})
        r = client.get("/admin/menu/state")
        data = r.json()
        assert data["is_open_override"] is True
        assert data["is_currently_open"] is True

    def test_強制關閉後is_currently_open為false(self, client):
        client.put("/admin/menu/open-override", json={"override": False})
        r = client.get("/admin/menu/state")
        assert r.json()["is_currently_open"] is False
