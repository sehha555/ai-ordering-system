# LoRA 訓練資料

> 生成日期：2026-03-08 ~ 03-09
> 總筆數：**997 筆** ✅（目標 1,000-1,100）
> 格式：OpenAI chat format JSONL（messages + tools）

## 檔案清單

| 檔案 | 類別 | 筆數 |
|------|------|------|
| `category_a_direct_call.jsonl` | A. 直接 call batch1 | 50 |
| `category_a2_riceball_egg_snack.jsonl` | A. 直接 call batch2（飯糰/蛋餅/點心） | 65 |
| `category_a3_carrier_drink_combo.jsonl` | A. 直接 call batch3（載體/飲料/套餐/果醬） | 65 |
| `category_a4_customization.jsonl` | A. 直接 call batch4（客製化/quantity/饅頭/套餐） | 65 |
| `category_a5_coverage.jsonl` | A. 直接 call batch5（邊界品項覆蓋） | 50 |
| `category_b_followup.jsonl` | B. 追問 batch1 | 30 |
| `category_b2_followup.jsonl` | B. 追問 batch2 | 60 |
| `category_cf_error_notool.jsonl` | C+F batch1 | 40 |
| `category_cf2_error_notool.jsonl` | C+F batch2 | 60 |
| `category_c3_okfalse.jsonl` | C. ok:false batch3（缺欄位/不存在/售完/空車結帳） | 50 |
| `category_d_slang.jsonl` | D. 俗稱 batch1 | 40 |
| `category_d2_slang.jsonl` | D. 俗稱 batch2 | 55 |
| `category_d3_slang.jsonl` | D. 俗稱 batch3（飲料簡稱/食物俗稱/歧義確認） | 55 |
| `category_e_multi_item.jsonl` | E. 多品項 batch1 | 35 |
| `category_e2_multi_item.jsonl` | E. 多品項 batch2 | 60 |
| `category_e3_multi_item.jsonl` | E. 多品項 batch3（連續call/追問/大單） | 55 |
| `category_fbg_final.jsonl` | F+B+G 收尾（離題45/追問10/風格10） | 65 |
| `category_g_reply_style.jsonl` | G. 回覆風格 batch1 | 30 |
| `category_g2_reply_style.jsonl` | G. 回覆風格 batch2 | 60 |
| `samples.jsonl` | 初始樣本 | 7 |
| **`all_training_data.jsonl`** | **全部合併** | **997** |

## Tool 使用統計

| Tool | 出現次數 |
|------|----------|
| finalize_order | 911 |
| add_drink | 364 |
| add_riceball | 269 |
| add_carrier | 254 |
| add_egg_pancake | 201 |
| add_snack | 181 |
| add_combo | 89 |
| query_menu | 23 |

## 各類別進度

| 類別 | 現有 | 目標 | 達成率 |
|------|------|------|--------|
| A 直接 call | 295 | 300 | 98% |
| B 追問 | 100 | 100 | 100% |
| C ok:false | 100 | 100 | 100% |
| D 俗稱 | 150 | 150 | 100% |
| E 多品項 | 150 | 150 | 100% |
| F 不 call | 95 | 100 | 95% |
| G 回覆風格 | 100 | 100 | 100% |
| **合計** | **997** | **~1,000** | **100%** |

## 品質檢查

- [x] 997/997 筆 JSON 格式合法
- [x] arguments 全部是 JSON object（合併時自動修復 15 筆 stringified）
- [x] 901/997 筆含 finalize_order（96 筆為 F 類不點餐場景）
- [x] 每個 tool_calls 陣列只含 1 個 call
