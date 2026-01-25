import pytest
import uuid
import os
import time
from fastapi.testclient import TestClient
from src.dm.dialogue_manager import DialogueManager
from src.repository.order_repository import OrderRepository

# 這些是持有 order_repo 單例引用的模組
import src.repository.order_repository as repo_mod
import src.api.app as api_mod
import src.dm.dialogue_manager as dm_mod

def get_unique_test_db():
    return f"test_orders_{uuid.uuid4().hex[:8]}.db"

@pytest.fixture
def test_env():
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
    from src.api.app import app
    # 強制重設 client 內部狀態
    return TestClient(app)

def test_order_persistence_on_submitted(test_env):
    dm = DialogueManager()
    sid = str(uuid.uuid4())
    dm.handle(sid, "我要一個薯餅")
    dm.handle(sid, "結帳")
    dm.handle(sid, "確定")
    
    orders = test_env.list_orders()
    assert len(orders) == 1
    assert orders[0]["total_price"] == 20

def test_api_security_unauthorized(client):
    # Missing header
    response = client.get("/orders")
    assert response.status_code == 401

    # Invalid key
    response = client.get("/orders", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401

def test_api_get_order_success(client, test_env):
    dm = DialogueManager()
    sid = str(uuid.uuid4())
    dm.handle(sid, "我要一個熱狗")
    dm.handle(sid, "結帳")
    dm.handle(sid, "對")
    
    session = dm.store.get(sid)
    order_id = session["order_payload"]["order_id"]
    
    response = client.get(f"/orders/{order_id}", headers={"X-API-Key": "yuan-secret-key"})
    assert response.status_code == 200
    assert response.json()["order_id"] == order_id

def test_api_get_order_invalid_format(client):
    response = client.get("/orders/BAD_ID_!", headers={"X-API-Key": "yuan-secret-key"})
    assert response.status_code == 400

def test_api_list_orders_filtering(client, test_env):
    dm = DialogueManager()
    for _ in range(2):
        sid = str(uuid.uuid4())
        dm.handle(sid, "我要一個薯餅")
        dm.handle(sid, "結帳")
        dm.handle(sid, "是")
        
    response = client.get("/orders", headers={"X-API-Key": "yuan-secret-key"})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
