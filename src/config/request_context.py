# src/config/request_context.py
"""HTTP Request 上下文 — 用 ContextVar 在 async 環境追蹤 request_id"""

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="no-request")


def get_request_id() -> str:
    return request_id_var.get()
