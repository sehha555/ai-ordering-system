"""
菜單管理 Admin API Router

提供後台管理介面所需的端點：
- 查詢完整菜單狀態（售完、連動、營業時間）
- 更新品項 / 分類售完狀態
- 一鍵恢復全部
- 更新營業時間與強制開關
"""

import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.tools.menu import menu_state_service
from src.config.menu_constants import build_menu_categories

router = APIRouter(prefix="/admin", tags=["admin"])

# ── 菜單資料路徑（讀取所有品項名稱供驗證用）────────────────────────────
_MENU_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "menu", "menu_all.json",
)


def _load_all_item_names() -> set[str]:
    """讀取 menu_all.json，回傳所有品項名稱集合（用於驗證品項是否存在）。"""
    with open(_MENU_PATH, "r", encoding="utf-8-sig") as f:
        items = json.load(f)
    return {item["name"] for item in items}


# ── Request Body 型別 ────────────────────────────────────────────────────

class ItemSoldOutRequest(BaseModel):
    """品項售完更新請求"""
    name: str
    sold_out: bool


class CategorySoldOutRequest(BaseModel):
    """分類售完更新請求"""
    key: str
    sold_out: bool


class BusinessHoursRequest(BaseModel):
    """營業時間更新請求（格式 HH:MM）"""
    open: str
    close: str


class OpenOverrideRequest(BaseModel):
    """強制開/關/自動請求。override=True 強制開、False 強制關、None 回自動。"""
    override: Optional[bool]


# ── 端點 ─────────────────────────────────────────────────────────────────


@router.get("/menu/state")
async def get_menu_state():
    """
    取得完整菜單管理狀態。

    回傳：
    - sold_out_items：品項級售完清單（原始設定值）
    - sold_out_categories：分類級售完字典（原始設定值）
    - effective_sold_out：套用連動規則後的最終售完清單
    - combo_status：各套餐可用狀態
    - business_hours：營業時間設定
    - is_currently_open：目前是否營業
    - is_open_override：強制開/關/自動（True/False/null）
    - categories：分類菜單列表，格式同 /api/menu
    """
    state = menu_state_service.get_state()
    effective = menu_state_service.get_effective_sold_out()
    combo_status = menu_state_service.get_effective_combo_status()
    currently_open = menu_state_service.is_currently_open()
    categories = build_menu_categories()

    return {
        "sold_out_items": state.get("sold_out_items", []),
        "sold_out_categories": state.get("sold_out_categories", {}),
        "effective_sold_out": effective,
        "combo_status": combo_status,
        "business_hours": state.get("business_hours", {}),
        "is_currently_open": currently_open,
        "is_open_override": state.get("is_open_override"),
        "categories": categories,
    }


@router.put("/menu/sold-out/item")
async def update_item_sold_out(body: ItemSoldOutRequest):
    """
    更新單一品項售完狀態。

    品項名稱必須存在於 menu_all.json，否則回 400。
    """
    # 驗證品項是否存在
    all_names = _load_all_item_names()
    if body.name not in all_names:
        raise HTTPException(
            status_code=400,
            detail=f"品項不存在：{body.name}",
        )

    menu_state_service.set_item_sold_out(body.name, body.sold_out)
    return {"ok": True, "name": body.name, "sold_out": body.sold_out}


@router.put("/menu/sold-out/category")
async def update_category_sold_out(body: CategorySoldOutRequest):
    """
    更新分類售完狀態。

    key 必須是合法的分類控制 key（定義於 menu_state_service），否則回 400。
    """
    try:
        menu_state_service.set_category_sold_out(body.key, body.sold_out)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "key": body.key, "sold_out": body.sold_out}


@router.post("/menu/reset-sold-out")
async def reset_sold_out():
    """一鍵恢復全部售完：清空品項清單、所有分類設回 False。"""
    menu_state_service.reset_all_sold_out()
    return {"ok": True, "message": "所有售完狀態已恢復"}


@router.put("/menu/business-hours")
async def update_business_hours(body: BusinessHoursRequest):
    """
    更新營業時間。

    open / close 格式為 HH:MM（如 "06:00"）。
    格式不合法時回 400。
    """
    # 簡單格式驗證：HH:MM
    import re
    pattern = re.compile(r"^\d{2}:\d{2}$")
    if not pattern.match(body.open) or not pattern.match(body.close):
        raise HTTPException(
            status_code=400,
            detail="時間格式必須為 HH:MM（如 06:00）",
        )

    menu_state_service.set_business_hours(body.open, body.close)
    return {"ok": True, "open": body.open, "close": body.close}


@router.put("/menu/open-override")
async def update_open_override(body: OpenOverrideRequest):
    """
    設定強制開/關/自動。

    override=True  → 強制營業
    override=False → 強制休息
    override=null  → 回到自動（依照 business_hours 判斷）
    """
    menu_state_service.set_open_override(body.override)
    return {"ok": True, "override": body.override}
