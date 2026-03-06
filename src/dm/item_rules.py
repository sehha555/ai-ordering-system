"""品項規則單一來源 - 同時驅動 LLM prompt 和後端驗證"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ItemRule:
    prompt_label: str            # 顯示在 prompt 的標籤，如「飯糰」
    required: list[str]          # 必填欄位名稱
    optional: list[str]          # 選填欄位名稱
    prompt_desc: str             # 注入 system prompt 的文字
    missing_prompts: dict[str, str]  # field → 追問文字


ITEM_RULES: dict[str, ItemRule] = {
    "riceball": ItemRule(
        prompt_label="飯糰",
        required=["flavor", "rice"],
        optional=["spicy", "extra_egg"],
        prompt_desc="必填：口味、米種。辣菜脯預設不加，加蛋預設蔥蛋不用問。",
        missing_prompts={
            "flavor": "飯糰什麼口味",
            "rice": "紫米白米還是混米",
        },
    ),
    "drink": ItemRule(
        prompt_label="飲料",
        required=["flavor", "size", "temp"],
        optional=[],
        prompt_desc="必填：品名、杯型（中/大）、溫度（冰/溫）。甜度不用問。",
        missing_prompts={
            "flavor": "什麼飲料",
            "size": "大杯還是中杯",
            "temp": "冰的還是溫的",
        },
    ),
    "carrier": ItemRule(
        prompt_label="載體（吐司/漢堡/饅頭）",
        required=["carrier", "flavor"],
        optional=[],
        prompt_desc="必填：載體種類（吐司/漢堡/饅頭）、配料口味。只說配料未說載體就追問。",
        missing_prompts={
            "carrier": "吐司還是漢堡",
            "flavor": "什麼口味",
        },
    ),
    "egg_pancake": ItemRule(
        prompt_label="蛋餅",
        required=["flavor"],
        optional=[],
        prompt_desc="必填：口味。",
        missing_prompts={"flavor": "蛋餅什麼口味"},
    ),
    "jam_toast": ItemRule(
        prompt_label="果醬吐司",
        required=["flavor"],
        optional=["size"],
        prompt_desc="必填：口味（草莓/花生/蒜香/奶酥/巧克力）。",
        missing_prompts={"flavor": "果醬吐司什麼口味 草莓花生蒜香奶酥巧克力"},
    ),
    "snack": ItemRule(
        prompt_label="點心",
        required=[],
        optional=[],
        prompt_desc="無必填，直接加入購物車。",
        missing_prompts={},
    ),
    "combo": ItemRule(
        prompt_label="套餐",
        required=["combo_name", "temp"],
        optional=["rice", "flavor"],
        prompt_desc="主餐固定不能改。必填：飲料溫度。各套餐額外必填見工具回饋。",
        missing_prompts={
            "combo_name": "套餐名稱是什麼",
            "temp": "飲料冰的還是溫的",
        },
    ),
}

# 套餐個別額外必填（從 tool_registry.py 搬來）
COMBO_REQUIREMENTS: dict[str, dict] = {
    "套餐二": {"needs_rice": True},
    "套餐五": {"needs_mantou_flavor": True},
    "套餐六": {"needs_noodle_flavor": True},
    "套餐七": {"needs_noodle_flavor": True},
    "套餐B": {"needs_toast_flavor": True},
    "兒童餐": {"needs_jam_flavor": True},
}


def check_combo_required(
    combo_name: Optional[str],
    temp: Optional[str],
    flavor: Optional[str],
    rice: Optional[str],
    customization: Optional[str],  # noqa: ARG001 — 保留簽名相容性
) -> Optional[str]:
    """檢查套餐必填欄位，回傳缺少的追問訊息，全齊回 None"""
    if not combo_name:
        return "套餐名稱是什麼"

    missing_parts = []

    # 所有套餐都需要飲料溫度
    if not temp:
        missing_parts.append("飲料冰的還是溫的")

    # 個別套餐的額外需求
    reqs = COMBO_REQUIREMENTS.get(combo_name, {})

    if reqs.get("needs_rice") and not rice:
        missing_parts.append("飯糰要紫米白米還是混米")

    if reqs.get("needs_mantou_flavor") and not flavor:
        missing_parts.append("饅頭要什麼口味")

    if reqs.get("needs_noodle_flavor") and not flavor:
        missing_parts.append("鐵板麵要黑椒蘑菇義大利還是咖哩")

    if reqs.get("needs_toast_flavor") and not flavor:
        missing_parts.append("厚片要什麼口味 花生巧克力奶酥蒜香草莓")

    if reqs.get("needs_jam_flavor") and not flavor:
        missing_parts.append("果醬吐司要什麼口味 草莓花生巧克力")

    if not missing_parts:
        return None

    return " ".join(missing_parts)


def generate_item_logic() -> str:
    """生成注入 system prompt 的品項邏輯段落"""
    sections = [
        f"## {rule.prompt_label}\n{rule.prompt_desc}"
        for rule in ITEM_RULES.values()
    ]
    return "\n\n".join(sections)
