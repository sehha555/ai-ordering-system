# Combo Aliases Configuration Documentation

This file documents the `combo_aliases.json` configuration.

## Manual Aliases

Mapping from simplified/user-spoken terms to the specific "Canonical Name" found in `menu_all.json`.

| Alias | Target (Canonical Name) | Reason / Source |
| :--- | :--- | :--- |
| **薯條** | 香酥脆薯 | Combo A/B/C/D/E and Kids Meal use "薯條" in description, but menu item is "香酥脆薯". |
| **紅茶** | 精選紅茶(中) | Common shorthand. Maps to medium by default as a safe fallback or per combo usage (e.g., Kids Meal uses medium). Note: Some combos use Large, but `remove_tokens` handles explicit "(大)". |
| **綠茶** | 無糖清香綠茶(中) | Shorthand for standard Green Tea. |
| **奶茶** | 純鮮奶茶(中) | Shorthand for Milk Tea. |
| **豆漿** | 有糖豆漿(中) | Shorthand. Default to Sweetened Medium. |
| **米漿** | 花生糙米漿(中) | Shorthand. |
| **熱狗** | 熱狗(3條) | Combo B uses "熱狗*3", menu item is "熱狗(3條)". |
| **雞塊** | 麥克雞塊(5個) | Kids Meal/Combo C use "雞塊*4", menu item is "麥克雞塊(5個)". |
| **蘿蔔糕** | 港式蘿蔔糕 | Combo 4 uses "蘿蔔糕二片", menu item is "港式蘿蔔糕". |
| **煎餃** | 煎餃(8顆) | General matching. |
| **十穀漿** | 十穀漿(中) | Combo 2 uses "十穀漿", matches "十穀漿(中)" or "十穀漿(大)". Mapping to Medium as base. |

## Normalize Rules

- **Remove Tokens**: "傳統", "有糖", "無糖", "精選", "純", "黑糖", "+豆漿", "清香", "純鮮奶", "咖啡", "茶", "(大)", "(中)", "(小)".
  - *Reason*: To allow loose matching of drink names and sizes within combo strings.
- **Regex Removals**: `\(.*\)`
  - *Reason*: To strip any remaining parenthetical info (like count or detailed specs) when strictly matching names.

## Allow Single Item Keywords

Keywords that should be treated as Single Items if they appear alone, preventing them from triggering a partial Combo match (if they happen to share a name with a combo-exclusive part, though less likely now with robust aliases).

- 薯餅
- 薯條
- 雞塊
- 熱狗
- 煎餃
- 蘿蔔糕
