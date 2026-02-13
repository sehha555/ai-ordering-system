import pytest
import uuid
import os
import time
from fastapi.testclient import TestClient
from src.dm.dialogue_manager import DialogueManager
from src.repository.order_repository import OrderRepository

# 持有 order_repo 單例引用的模組
import src.repository.order_repository as repo_mod
import src.api.app as api_mod
import src.dm.dialogue_manager as dm_mod


def get_unique_test_db():
    return f"test_orders_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture
def test_env():
    """測試環境 fixture - 設定獨立的測試資料庫"""
    db_path = get_unique_test_db()
    test_repo = OrderRepository(db_path=db_path)

    # 備份原始單例
    old_repos = {
        "repo": repo_mod.order_repo,
        "api": api_mod.order_repo,
        "dm": dm_mod.order_repo
    }

    # 全面注入測試用 repo
    repo_mod.order_repo = test_repo
    api_mod.order_repo = test_repo
    dm_mod.order_repo = test_repo

    yield test_repo

    # 復原單例
    repo_mod.order_repo = old_repos["repo"]
    api_mod.order_repo = old_repos["api"]
    dm_mod.order_repo = old_repos["dm"]

    # 清理檔案 (retry Windows 鎖定)
    for _ in range(10):
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
            break
        except PermissionError:
            time.sleep(0.1)


@pytest.fixture
def client(test_env):
    """API 客戶端 fixture"""
    from src.api.app import app
    return TestClient(app)


# ============================================================================
# 12 個 E2E API 煙霧測試
# ============================================================================

API_KEY_HEADER = {"X-API-Key": "yuan-secret-key"}


def test_healthz(client):
    """1. GET /healthz - 健康檢查"""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_store_config(client):
    """2. GET /api/store-config - 取得店家設定"""
    r = client.get("/api/store-config")
    assert r.status_code == 200
    data = r.json()
    assert "store" in data
    assert "ui" in data


def test_menu(client):
    """3. GET /api/menu - 取得菜單"""
    r = client.get("/api/menu")
    assert r.status_code == 200
    data = r.json()
    assert "categories" in data
    assert len(data["categories"]) > 0
    # 檢查結構
    cat = data["categories"][0]
    assert "name" in cat
    assert "items" in cat
    assert len(cat["items"]) > 0
    assert "name" in cat["items"][0]
    assert "price" in cat["items"][0]


def test_llm_status(client):
    """4. GET /llm/test - 測試 LLM 服務狀態"""
    r = client.get("/llm/test", headers=API_KEY_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ready", "error")


def test_asr_status(client):
    """5. GET /asr/test - 測試 ASR 服務狀態"""
    r = client.get("/asr/test", headers=API_KEY_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ready", "not_loaded")


def test_tts_status(client):
    """6. GET /tts/test - 測試 TTS 服務狀態"""
    r = client.get("/tts/test", headers=API_KEY_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ready", "not_loaded")


def test_dialogue_text(client):
    """7. POST /dialogue/text - 文本對話"""
    sid = str(uuid.uuid4())
    r = client.post("/dialogue/text",
                    json={"session_id": sid, "text": "你好"},
                    headers=API_KEY_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert "response" in data
    assert data["session_id"] == sid
    # status 可能是 ok 或 error（取決於 LLM 服務是否啟動）


def test_cart_summary(client, test_env):
    """8. GET /cart/summary - 取得購物車摘要"""
    from src.api.app import _session_store
    sid = str(uuid.uuid4())
    session = _session_store.get(sid)
    # 直接放商品到 cart - 使用正確的 itemtype 格式和完整品項名稱
    session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    r = client.get(f"/cart/summary?session_id={sid}", headers=API_KEY_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["cart_count"] == 1


def test_checkout(client, test_env):
    """9. POST /api/checkout - 完整結帳流程"""
    from src.api.app import _session_store
    sid = str(uuid.uuid4())
    session = _session_store.get(sid)
    # 使用正確的 itemtype 格式和完整品項名稱
    session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    r = client.post("/api/checkout", json={
        "session_id": sid,
        "dine_type": "dine-in",
        "payment_method": "cash"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "order_number" in data
    assert "order_id" in data
    assert data["total"] > 0


def test_get_order(client, test_env):
    """10. GET /orders/{id} - 查詢單筆訂單"""
    from src.api.app import _session_store
    sid = str(uuid.uuid4())
    session = _session_store.get(sid)
    # 使用正確的 itemtype 格式和完整品項名稱
    session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    # 先結帳
    r = client.post("/api/checkout", json={
        "session_id": sid,
        "dine_type": "take-out",
        "payment_method": "cash"
    })
    order_id = r.json()["order_id"]
    # 查詢
    r = client.get(f"/orders/{order_id}", headers=API_KEY_HEADER)
    assert r.status_code == 200
    assert r.json()["order_id"] == order_id


def test_list_orders(client, test_env):
    """11. GET /orders - 列表查詢訂單"""
    from src.api.app import _session_store
    # 建立 2 筆訂單
    for _ in range(2):
        sid = str(uuid.uuid4())
        session = _session_store.get(sid)
        # 使用正確的 itemtype 格式和完整品項名稱
        session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
        client.post("/api/checkout", json={
            "session_id": sid,
            "dine_type": "dine-in",
            "payment_method": "cash"
        })
    r = client.get("/orders", headers=API_KEY_HEADER)
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 2


def test_unauthorized_access(client):
    """12. 未授權存取測試"""
    # 無 header
    r = client.get("/orders")
    assert r.status_code in (401, 403)
    # 錯誤 key
    r = client.get("/orders", headers={"X-API-Key": "wrong-key"})
    assert r.status_code in (401, 403)
    # /llm/test 也需要 key
    r = client.get("/llm/test")
    assert r.status_code in (401, 403)
