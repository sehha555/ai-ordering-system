"""認證相關依賴"""

import logging
from typing import Optional

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from src.config.settings import settings

logger = logging.getLogger(__name__)

API_KEY = settings.API_KEY
if not API_KEY:
    logger.warning("[AUTH] API_KEY 未設定，API Key 驗證已停用（僅限開發環境）")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return "dev"
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key


def get_api_key_or_token(
    api_key: str = Security(api_key_header),
    token: Optional[str] = Query(None, alias="token"),
):
    """同時接受 header 和 query param token（EventSource 不支援 header）"""
    if not API_KEY:
        return "dev"
    key = api_key or token
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return key
