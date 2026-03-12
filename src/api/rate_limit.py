# src/api/rate_limit.py
"""共用限流器 — 避免 router 模組對 app.py 的循環依賴"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
