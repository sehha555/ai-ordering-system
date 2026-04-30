"""品項規則單一來源 - 同時驅動 LLM prompt 和後端驗證"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.config.config_loader import load_json_config


@dataclass
class ItemRule:
    prompt_label: str  # 顯示在 prompt 的標籤，如「飯糰」
    required: list[str]  # 必填欄位名稱
    optional: list[str]  # 選填欄位名稱
    prompt_desc: str  # 注入 system prompt 的文字
    missing_prompts: dict[str, str]  # field → 追問文字


_rules_cfg = load_json_config("item_rules.json")

ITEM_RULES: dict[str, ItemRule] = {k: ItemRule(**v) for k, v in _rules_cfg["item_rules"].items()}

# 套餐個別額外必填
COMBO_REQUIREMENTS: dict[str, dict] = _rules_cfg["combo_requirements"]


_chase = _rules_cfg["combo_chase_prompts"]


def check_combo_required(
    combo_name: Optional[str],
    temp: Optional[str],
    flavor: Optional[str],
    rice: Optional[str],
    customization: Optional[str],  # noqa: ARG001 — 保留簽名相容性
) -> tuple[Optional[str], list[str]]:
    """檢查套餐必填欄位，回傳 (追問訊息, 缺少欄位 list)，全齊回 (None, [])"""
    if not combo_name:
        return _chase["combo_name_missing"], ["combo_name"]

    missing_parts: list[str] = []
    missing_fields: list[str] = []

    if not temp:
        missing_parts.append(_chase["temp"])
        missing_fields.append("temp")

    reqs = COMBO_REQUIREMENTS.get(combo_name, {})

    if reqs.get("needs_rice") and not rice:
        missing_parts.append(_chase["needs_rice"])
        missing_fields.append("rice")

    flavor_chase_keys = (
        "needs_mantou_flavor",
        "needs_noodle_flavor",
        "needs_toast_flavor",
        "needs_jam_flavor",
    )
    for key in flavor_chase_keys:
        if reqs.get(key) and not flavor:
            missing_parts.append(_chase[key])
            missing_fields.append("flavor")
            break

    if not missing_parts:
        return None, []

    return " ".join(missing_parts), missing_fields


def generate_item_logic() -> str:
    """生成注入 system prompt 的品項邏輯段落"""
    sections = [f"## {rule.prompt_label}\n{rule.prompt_desc}" for rule in ITEM_RULES.values()]
    return "\n\n".join(sections)
