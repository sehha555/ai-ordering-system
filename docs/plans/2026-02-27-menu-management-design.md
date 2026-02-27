# 菜單管理系統設計

> 日期：2026-02-27
> 狀態：設計確認，待實作

## 目標

讓店家能透過 web 介面管理品項售完狀態和營業時間，並讓 LLM 感知品項狀態。

## 範圍

### 現在做
- 品項售完/恢復 toggle（品項級 + 分類級控制）
- 分類級控制（載體、米種、饅頭種類、鐵板麵麵種、蔥抓餅）
- 套餐自動連動（主餐售完 → 套餐關）
- 一鍵恢復全部售完
- 營業時間設定（開始/結束）
- 手動 override 營業狀態（強制開/關/自動）
- LLM system prompt 注入售完品項
- 菜單更新：新增白花捲、芋頭饅頭、芋泥包；黑饅頭→黑糖饅頭、黑花捲→黑糖花捲

### 不做（未來）
- 顧客端售完顯示
- 價格調整 / 品項上下架
- 認證系統（Phase 2 上雲端時加）
- 自然語言管理（「薯餅賣完了」→ 自動標售完）
- 多店 / 分帳號（屆時升級 SQLite/PostgreSQL）
- LLM 主動推薦替代品（售完時推薦類似品項）

## 菜單變更

`menu_all.json` 饅頭分類修改：
- 黑饅頭 → **黑糖饅頭**（改名）
- 黑花捲 → **黑糖花捲**（改名）
- 新增：**白花捲** $15
- 新增：**芋頭饅頭** $15
- 新增：**芋泥包** $15

## 設計

### Part 1：資料層

**新增檔案：`src/tools/menu/menu_state.json`**

```json
{
  "sold_out_items": [],
  "sold_out_categories": {
    "carrier_toast": false,
    "carrier_burger": false,
    "carrier_thick_toast": false,
    "rice_purple": false,
    "rice_white": false,
    "mantou_black_sugar": false,
    "mantou_white": false,
    "mantou_black_sugar_roll": false,
    "mantou_white_roll": false,
    "mantou_taro": false,
    "noodle_oil": false,
    "noodle_udon": false,
    "scallion_pancake": false
  },
  "business_hours": {
    "open": "06:00",
    "close": "14:00"
  },
  "is_open_override": null
}
```

**分類級控制項（13 個開關）：**

| Key | 名稱 | 關掉後影響 |
|-----|------|-----------|
| `carrier_toast` | 吐司 | 所有 XX 蛋吐司 + 果醬薄片 + 套餐A、D、兒童餐 |
| `carrier_burger` | 漢堡 | 所有 XX 蛋漢堡 + 套餐E |
| `carrier_thick_toast` | 厚片 | 果醬厚片 + 套餐B |
| `rice_purple` | 紫米 | 紫米飯糰 + 混米自動關 |
| `rice_white` | 白米 | 白米飯糰 + 混米自動關 |
| `mantou_black_sugar` | 黑糖饅頭 | 黑糖饅頭品項 |
| `mantou_white` | 白饅頭 | 白饅頭品項 |
| `mantou_black_sugar_roll` | 黑糖花捲 | 黑糖花捲品項 |
| `mantou_white_roll` | 白花捲 | 白花捲品項 |
| `mantou_taro` | 芋頭饅頭 | 芋頭饅頭品項 |
| `noodle_oil` | 油麵 | 黑椒/蘑菇/義大利鐵板麵的油麵選項 |
| `noodle_udon` | 烏龍麵 | 咖哩烏龍直接關 + 其他鐵板麵的烏龍選項 |
| `scallion_pancake` | 蔥抓餅 | 蔥抓餅(原味) + 蔥抓餅(加蛋) |

### Part 1.5：套餐連動規則

**核心原則：主餐沒了 → 關套餐。配餐/飲料沒了 → 不關，可替代。**

| 套餐 | 主餐（不可變動） | 關掉條件 |
|------|-----------------|----------|
| 套餐一 | 醬燒肉片蛋餅 | 醬燒肉片蛋餅售完 |
| 套餐二 | 源味飯糰 | 紫米+白米都關（所有米種不可用） |
| 套餐三 | 高麗菜蛋餅 | 高麗菜蛋餅售完 |
| 套餐四 | 蘿蔔糕 | 蘿蔔糕售完 |
| 套餐五 | 起司蛋饅頭 | 5 種饅頭都關 |
| 套餐六 | 鐵板麵+肉片 | 油麵+烏龍都關 |
| 套餐七 | 鐵板麵+無骨雞排 | 油麵+烏龍都關 OR 無骨雞排售完 |
| 套餐A | 總匯三明治 | 吐司關 |
| 套餐B | 香腸厚片 | 厚片關 |
| 套餐C | 義大利肉醬麵 | 油麵+烏龍都關 |
| 套餐D | 烤吐司+培根 | 吐司關 |
| 套餐E | 無骨雞排堡 | 漢堡關 OR 無骨雞排售完 |
| 兒童餐 | 果醬吐司 | 吐司關 |

**連動規則引擎：**

```
規則 1：載體關 → 該載體所有品項 + 相關套餐關
  吐司關 → 所有吐司品項 + 果醬薄片 + 套餐A、D、兒童餐
  漢堡關 → 所有漢堡品項 + 套餐E
  厚片關 → 果醬厚片 + 套餐B

規則 2：米種連動
  紫米關 → 混米自動關
  白米關 → 混米自動關
  兩個都關 → 套餐二關

規則 3：饅頭種類 — 全關才關套餐
  5 種都關 → 套餐五關
  還有任一種 → 套餐五不關（選項變少，LLM 告知）

規則 4：鐵板麵麵種 — 全關才關套餐
  油麵+烏龍都關 → 套餐六、七、C 關
  還有一種 → 套餐不關（選項變少，LLM 告知）
  咖哩烏龍固定烏龍麵 → 烏龍關 = 咖哩烏龍直接關

規則 5：品項售完 → 連動套餐主餐
  醬燒肉片蛋餅售完 → 套餐一關
  高麗菜蛋餅售完 → 套餐三關
  蘿蔔糕售完 → 套餐四關
  無骨雞排售完 → 套餐七、E 關

規則 6：蔥抓餅關 → 蔥抓餅(原味) + 蔥抓餅(加蛋) 關（無套餐影響）

規則 7：飲料/配餐售完 → 套餐不關，LLM 告知可替代
```

**新增 Service：`src/tools/menu/menu_state_service.py`**

| 方法 | 功能 |
|------|------|
| `get_state()` | 取得完整狀態 |
| `get_sold_out_items() -> list[str]` | 取得品項級售完清單 |
| `get_sold_out_categories() -> dict` | 取得分類級售完狀態 |
| `set_item_sold_out(name, sold_out: bool)` | 設定單品售完狀態 |
| `set_category_sold_out(key, sold_out: bool)` | 設定分類售完狀態 |
| `reset_all_sold_out()` | 一鍵恢復全部（品項+分類） |
| `get_effective_sold_out() -> list[str]` | 計算最終售完清單（含連動） |
| `get_effective_combo_status() -> dict` | 計算套餐可用狀態 |
| `get_business_hours()` | 取得營業時間 |
| `set_business_hours(open, close)` | 設定營業時間 |
| `is_currently_open() -> bool` | 判斷目前是否營業 |
| `set_open_override(override)` | 設定營業狀態 override |

核心方法 `get_effective_sold_out()` 負責套用所有連動規則，回傳最終的售完品項清單。

### Part 2：API 端點

**新增：`src/api/admin_router.py`**

| 方法 | 端點 | 功能 |
|------|------|------|
| `GET` | `/admin/menu/state` | 取得完整狀態（菜單 + 售完 + 連動結果 + 營業時間） |
| `PUT` | `/admin/menu/sold-out/item` | 更新品項售完 `{name, sold_out: bool}` |
| `PUT` | `/admin/menu/sold-out/category` | 更新分類售完 `{key, sold_out: bool}` |
| `POST` | `/admin/menu/reset-sold-out` | 一鍵恢復全部 |
| `PUT` | `/admin/menu/business-hours` | 更新營業時間 `{open, close}` |
| `PUT` | `/admin/menu/open-override` | 強制開/關/自動 `{override: true\|false\|null}` |

掛載：`app.py` → `app.include_router(admin_router, prefix="/admin")`
Next.js proxy：`next.config.ts` rewrites 加 `/admin/*` → backend

### Part 3：LLM 感知

修改 `src/dm/system_prompts.py` 的 `build_system_prompt()`：

- 從 `menu_state_service.get_effective_sold_out()` 取得最終售完清單（含連動）
- 從 `menu_state_service.get_effective_combo_status()` 取得套餐狀態
- 注入格式：

```
【售完資訊】
售完品項：甜飯糰、鐵板麵(大)、蔥抓餅(原味)、蔥抓餅(加蛋)
售完分類：吐司（所有吐司品項不可點）、紫米（混米也不可用）
不可用套餐：套餐A、套餐D、兒童餐
選項限制：饅頭目前只有黑糖饅頭、白花捲可選；鐵板麵目前只能選油麵
顧客點售完品項時，請告知已售完。
```

- 零售完 = 不注入（不浪費 token）
- 注意：此為動態內容，放在 system prompt 尾段避免破壞 prefix cache

### Part 4：前端管理頁面

**新增：`src/frontend_next/app/admin/menu/page.tsx`**

UI 結構（參考早點 Morning 風格）：

```
┌─────────────────────────────┐
│  🏪 菜單管理                │
│  營業時間: 06:00 - 14:00 ✏️  │
│  [營業中 🟢] / [已休息 🔴]   │
├─────────────────────────────┤
│  [一鍵恢復全部]              │
├─────────────────────────────┤
│  ── 分類控制 ──              │
│  載體: [吐司🟢] [漢堡🟢] [厚片🟢] │
│  米種: [紫米🟢] [白米🟢]      │
│  饅頭: [黑糖🟢][白饅🟢][黑糖花捲🟢][白花捲🟢][芋頭🟢] │
│  鐵板麵: [油麵🟢] [烏龍麵🟢]  │
│  其他: [蔥抓餅🟢]            │
├─────────────────────────────┤
│  分類 pill tabs（橫向滑動）   │
│  [套餐] [飯糰] [蛋餅] ...   │
├─────────────────────────────┤
│  🍙 飯糰 (2 售完)           │
│  ┌───────────────────┬────┐ │
│  │ 甜飯糰       $35  │ 🔴 │ │
│  │ 鹹飯糰       $40  │ 🟢 │ │
│  │ 鮪魚飯糰     $55  │ 🟢 │ │
│  └───────────────────┴────┘ │
│                             │
│  🍱 套餐 (3 不可用)         │
│  ┌───────────────────┬────┐ │
│  │ 套餐A (吐司關)    │ 🔒 │ │  ← 被連動鎖定，顯示原因
│  │ 套餐B         $130│ 🟢 │ │
│  └───────────────────┴────┘ │
└─────────────────────────────┘
```

- 分類控制區：pill 按鈕直接 toggle，綠色在售/紅色售完
- 品項列表：每個品項右側 toggle
- 被連動關閉的套餐顯示 🔒 + 原因（如「吐司關」）
- 分類 pill tabs 橫向滑動
- 營業時間點 ✏️ 彈出 time picker
- 營業狀態支援手動 override
- 手機優先 responsive layout
- 技術：React 19 + Tailwind + 品牌色 `#729DAD`，不加新依賴

## 影響的現有檔案

| 檔案 | 改動 |
|------|------|
| `src/tools/menu/menu_all.json` | 饅頭改名 + 新增 3 品項 |
| `src/api/app.py` | 掛載 admin_router |
| `src/dm/system_prompts.py` | 注入售完資訊到 system prompt |
| `src/frontend_next/next.config.ts` | 加 `/admin/*` proxy rewrite |

## 新增檔案

| 檔案 | 說明 |
|------|------|
| `src/tools/menu/menu_state.json` | 售完狀態持久化 |
| `src/tools/menu/menu_state_service.py` | 狀態管理 + 連動規則引擎 |
| `src/api/admin_router.py` | 管理 API 端點 |
| `src/frontend_next/app/admin/menu/page.tsx` | 管理介面頁面 |

## 演化路徑

1. **現在**：單店 JSON → 管理介面 + LLM 感知 + 連動規則
2. **下一步**：LLM 主動推薦替代品（售完時推薦類似品項）
3. **之後**：自然語言管理（「薯餅賣完了」→ 自動標售完）
4. **多店**：升級 SQLite/PostgreSQL + 認證 + tenant 隔離
