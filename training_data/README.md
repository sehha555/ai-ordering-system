# LoRA 訓練資料

> 生成日期：2026-03-08 ~ 03-10
> 總筆數：**1,067 筆** ✅（目標 1,000-1,100）
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
| `category_h_edge_cases.jsonl` | H. 邊界場景（修正/跳轉/模糊/矛盾/改量/改結帳） | 70 |
| `samples.jsonl` | 初始樣本 | 7 |
| **`all_training_data.jsonl`** | **全部合併** | **1,067** |

## Tool 使用統計

| Tool | 出現次數 |
|------|----------|
| finalize_order | 984 |
| add_drink | 393 |
| add_riceball | 297 |
| add_carrier | 271 |
| add_egg_pancake | 224 |
| add_snack | 194 |
| add_combo | 89 |
| remove_from_cart | 25 |
| query_menu | 23 |

## 各類別進度

| 類別 | 筆數 | 說明 |
|------|------|------|
| A 直接 call | 295 | 各品項覆蓋 + 客製化 + quantity |
| B 追問 | 100 | 標準追問鏈 |
| C ok:false | 100 | 缺欄位/不存在/售完/空車結帳 |
| D 俗稱 | 150 | 飲料簡稱/食物俗稱/歧義確認 |
| E 多品項 | 150 | 2-5 品項連續 call |
| F 不 call | 95 | 離題/打招呼/沒有的東西 |
| G 回覆風格 | 100 | 簡潔回覆 + 結帳格式 |
| H 邊界場景 | 70 | 修正/品類跳轉/模糊回答/矛盾/追加減量/改結帳 |
| 初始樣本 | 7 | |
| **合計** | **1,067** | |

## 品質檢查

- [x] 1,067/1,067 筆 JSON 格式合法
- [x] arguments 全部是 JSON object（合併時自動修復 stringified）
- [x] 984/1,067 筆含 finalize_order（83 筆為 F 類不點餐場景）
- [x] remove_from_cart 場景覆蓋（25 筆）
- [ ] 菜單一致性驗證（flavor 值 vs menu_all.json）
- [ ] Schema required fields 驗證
- [ ] 執行驗證（arguments 能否通過 tool function）
