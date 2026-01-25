import os
import re
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from typing import List, Optional
from src.repository.order_repository import order_repo

app = FastAPI(title="Yuan Rice Ball Order API")

API_KEY = os.getenv("API_KEY", "yuan-secret-key")
api_key_header = APIKeyHeader(name="X-API-Key")

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key

def validate_order_id(order_id: str):
    if not re.match(r"^[A-Z0-9-]+$", order_id) or len(order_id) > 20:
        raise HTTPException(status_code=400, detail="Invalid Order ID format")

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/orders/{order_id}")
async def get_order(order_id: str, api_key: str = Depends(get_api_key)):
    validate_order_id(order_id)
    order = order_repo.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/orders")
async def list_orders(
    date: Optional[str] = None, 
    status: Optional[str] = None, 
    limit: int = 50, 
    offset: int = 0,
    api_key: str = Depends(get_api_key)
):
    orders = order_repo.list_orders(date=date, status=status, limit=limit, offset=offset)
    return {"items": orders, "count": len(orders)}
