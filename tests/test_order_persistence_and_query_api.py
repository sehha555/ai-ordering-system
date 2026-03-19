import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from src.repository.order_repository import OrderRepository

# 持有 order_repo 單例引用的模組
import src.repository.order_repository as repo_mod
import src.api.app as api_mod
import src.api.checkout_router as checkout_mod


def get_unique_test_db():
    return f"test_orders_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture
def test_env():
    from src.api.rate_limit import limiter

    limiter.reset()

    db_path = get_unique_test_db()
    test_repo = OrderRepository(db_path=db_path)

    # 備份原始單例
    old_repos = {
        "repo": repo_mod.order_repo,
        "api": api_mod.order_repo,
        "checkout": checkout_mod.order_repo,
    }

    # 全面注入測試用 repo
    repo_mod.order_repo = test_repo
    api_mod.order_repo = test_repo
    checkout_mod.order_repo = test_repo

    yield test_repo

    # 復原單例
    repo_mod.order_repo = old_repos["repo"]
    api_mod.order_repo = old_repos["api"]
    checkout_mod.order_repo = old_repos["checkout"]

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

    return TestClient(app)


API_KEY_HEADER = {"X-API-Key": "yuan-secret-key"}


def test_order_persistence_on_submitted(client, test_env):
    from src.api.app import _session_store

    sid = str(uuid.uuid4())
    session = _session_store.get(sid)
    session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    client.post(
        "/api/checkout",
        json={"session_id": sid, "dine_type": "dine-in", "payment_method": "cash"},
    )

    orders = test_env.list_orders()
    assert len(orders) == 1
    assert orders[0]["total_price"] == 20


def test_api_security_unauthorized(client, monkeypatch):
    """需設定 API_KEY 才會啟用驗證"""
    import src.api.auth as auth_mod

    monkeypatch.setattr(auth_mod, "API_KEY", "test-secret-key")

    response = client.get("/orders")
    assert response.status_code == 401

    response = client.get("/orders", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_api_get_order_success(client, test_env):
    from src.api.app import _session_store

    sid = str(uuid.uuid4())
    session = _session_store.get(sid)
    session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    r = client.post(
        "/api/checkout",
        json={"session_id": sid, "dine_type": "dine-in", "payment_method": "cash"},
    )
    order_id = r.json()["order_id"]

    response = client.get(f"/orders/{order_id}", headers=API_KEY_HEADER)
    assert response.status_code == 200
    assert response.json()["order_id"] == order_id


def test_api_get_order_invalid_format(client):
    response = client.get("/orders/BAD_ID_!", headers=API_KEY_HEADER)
    assert response.status_code == 400


def test_api_list_orders_filtering(client, test_env):
    from src.api.app import _session_store

    for _ in range(2):
        sid = str(uuid.uuid4())
        session = _session_store.get(sid)
        session["cart"] = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
        client.post(
            "/api/checkout",
            json={"session_id": sid, "dine_type": "dine-in", "payment_method": "cash"},
        )

    response = client.get("/orders", headers=API_KEY_HEADER)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
