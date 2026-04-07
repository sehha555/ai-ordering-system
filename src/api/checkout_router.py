# src/api/checkout_router.py
"""結帳 + 購物車 API Router"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from loguru import logger
from starlette.requests import Request

from src.api.auth import get_api_key
from src.api.rate_limit import limiter
from src.config.settings import settings
from src.dm import cart_manager
from src.repository.order_repository import order_repo
from src.services import container

router = APIRouter(tags=["checkout"])


class CheckoutRequest(BaseModel):
    """結帳請求"""

    session_id: str
    dine_type: str  # "dine-in" | "take-out"
    payment_method: str  # "cash" | "mobile"


@router.get("/cart/summary")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def get_cart_summary(request: Request, session_id: str, api_key: str = Depends(get_api_key)):
    """取得購物車摘要"""
    try:
        session = container.session_store.get(session_id)
        cart = session.get("cart", [])

        if not cart:
            return {
                "ok": True,
                "cart_count": 0,
                "items": [],
                "total_price": 0,
                "message": "購物車為空",
            }

        summary = cart_manager.build_cart_summary(cart, price_format="dollar")
        items = [
            {
                "index": entry["index"],
                "name": entry["name"],
                "quantity": entry["quantity"],
                "price": entry["price_str"],
            }
            for entry in summary["items"]
        ]
        total_price = summary["total_price"]

        return {
            "ok": True,
            "cart_count": len(cart),
            "items": items,
            "total_price": total_price,
            "message": f"購物車共 {len(cart)} 項，總計 ${total_price}",
        }

    except Exception:
        logger.exception("[CART] get_cart_summary 異常")
        return {"ok": False, "message": "內部錯誤", "items": [], "total_price": 0}


@router.post("/api/checkout")
@limiter.limit(settings.RATE_LIMIT_CHECKOUT)
async def checkout(request: Request, body: CheckoutRequest, api_key: str = Depends(get_api_key)):
    """
    處理結帳請求
    - 從 session_store 讀取購物車
    - 寫入訂單到 orders.db
    - 取餐號碼：每日遞增，最少兩位補零
    - 儲存對話紀錄（SQLite + JSON 檔）
    - 清空 session 的 llm_history 和購物車
    """
    try:
        session_id = body.session_id
        dine_type = body.dine_type
        payment_method = body.payment_method

        logger.info(
            "[CHECKOUT] 開始結帳: session_id={}, dine_type={}, payment={}",
            session_id,
            dine_type,
            payment_method,
        )

        # 1. 從 session_store 讀取購物車
        session = container.session_store.get(session_id)
        cart = session.get("cart", [])
        if not cart:
            raise HTTPException(status_code=400, detail="購物車是空的，無法結帳")
        llm_history = session.get("llm_history", [])

        logger.info("[CHECKOUT] 購物車: {} 項", len(cart))

        # 2. 計算總價
        total_price = cart_manager.calculate_cart_total(cart)

        logger.info("[CHECKOUT] 總計: ${}", total_price)

        # 3. 建立訂單（order_number 由 save_order_with_number 原子性取號）
        # order_id 必須只包含大寫字母、數字和連字符
        order_id = f"ORD-{datetime.now().strftime('%m%d')}-{str(uuid.uuid4())[:8].upper()}"

        order_payload = {
            "order_id": order_id,
            "session_id": session_id,
            "dine_type": dine_type,
            "payment_method": payment_method,
            "items": cart,
            "total_price": total_price,
            "status": "SUBMITTED",
            "created_at": datetime.now().isoformat(),
        }

        # 4. 原子性取號 + 寫入訂單
        order_number = order_repo.save_order_with_number(order_payload, session_id)
        logger.info("[CHECKOUT] 訂單已保存: {} 取餐號碼: {}", order_id, order_number)

        # 5. 儲存對話紀錄（JSON 檔）
        order_repo.save_conversation_log_json(
            session_id, order_number, cart, total_price, dine_type, llm_history
        )
        logger.info("[CHECKOUT] 對話紀錄已保存")

        # 7. 清空 session（llm_history 和購物車）
        session["llm_history"] = []
        session["cart"] = []
        container.session_store.set(session_id, session)  # Redis 回寫
        logger.debug("[CHECKOUT] Session 已清除")

        return {
            "status": "ok",
            "order_number": order_number,
            "order_id": order_id,
            "total": total_price,
            "dine_type": dine_type,
            "payment_method": payment_method,
        }

    except HTTPException:
        raise  # 保留已包裝的 HTTPException（如 400 空購物車）
    except Exception:
        logger.exception("[CHECKOUT] 結帳異常")
        raise HTTPException(status_code=500, detail="結帳處理失敗")
