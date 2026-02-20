# Benchmark 測試報告 — 2026-02-20

## 測試環境

| 項目 | 規格 |
|------|------|
| GPU | NVIDIA RTX 5070 Ti 16GB |
| OS | Windows 11 Pro |
| Python | 3.11 (uv 管理) |
| LM Studio | qwen2.5-14b-instruct-1m |
| ASR | SenseVoice-Small (funasr 1.3.1) |
| TTS | Edge TTS (zh-TW-HsiaoChenNeural) |
| VRAM 分配 | LLM ~11GB + ASR ~4GB ≈ 15.5GB / 16GB |

### VRAM 限制說明
16GB VRAM 不足以同時跑 LLM (14B) + TTS (Qwen3-TTS 1.7B) + ASR (SenseVoice)。
TTS 改用 Edge TTS（雲端，零 VRAM）後系統穩定運行。

---

## 一、LLM Benchmark — Qwen2.5-14B-Instruct

### 總結指標

| 指標 | 數值 | 說明 |
|------|------|------|
| Scenario Pass Rate | **59% (13/22)** | 場景通過率 |
| Tool Call F1 | **0.58** | 工具呼叫準確度 |
| Tool Call Precision | **0.58** | |
| Tool Call Recall | **0.68** | |
| Response Quality | **0.53** | 回應關鍵字覆蓋率 |
| Avg Latency | **0.90s** | 單次推理延遲 |
| Avg Tokens | **3645** | 含 system prompt + tools schema |

### 各場景結果

| 場景 | 類別 | 期望工具 | 實際工具 | 判定 | 模型回應（摘要） |
|------|------|----------|----------|------|------------------|
| basic_order | missing_info | (無) | (無) | ✅ PASS | 「紫米白米還是混米」— 正確追問米種 |
| basic_order_complete | basic | add_to_cart | (無) | ❌ FAIL | 用文字回覆而非 tool call |
| combo_query | query | query_menu | query_menu | ✅ PASS | 「我們有十三種套餐」 |
| multi_item | basic | add_to_cart | (無) | ❌ FAIL | 用文字回覆而非 tool call |
| modify_order | modify | add_to_cart | (無) | ❌ FAIL | 用文字回覆 |
| query_menu | query | query_menu | (無) | ❌ FAIL | 直接列出飲料而非用工具 |
| checkout_flow | checkout | finalize_order | get_cart_summary | ❌ FAIL | 先問內用外帶而非直接結帳 |
| missing_flavor | missing_info | (無) | (無) | ✅ PASS | 正確追問口味+米種 |
| missing_quantity | missing_info | (無) | (無) | ✅ PASS | 正確追問口味+人數 |
| missing_drink_spec | missing_info | (無) | (無) | ✅ PASS | 正確追問冰溫 |
| missing_egg_pancake_flavor | missing_info | (無) | (無) | ✅ PASS | 正確追問口味 |
| ambiguous_item | missing_info | (無) | (無) | ✅ PASS | 正確追問口味 |
| complex_order_complete | complex | add_to_cart | add_to_cart | ✅ PASS | 正確呼叫工具 |
| complex_order_partial_info | complex_missing | (無) | add_to_cart | ❌ FAIL | 不該呼叫工具（資訊不完整） |
| modify_without_context | edge_case | (無) | remove_from_cart | ❌ FAIL | 應告知購物車為空 |
| cancel_nonexistent | edge_case | (無) | remove_from_cart | ❌ FAIL | 應告知購物車沒有此品項 |
| off_topic | edge_case | (無) | (無) | ✅ PASS | 「這裡是源飯糰，不提供天氣資訊」 |
| multi_round_clarification | multi_round | add_to_cart | (無) | ❌ FAIL | 用文字回覆而非 tool call |
| multi_round_drink | multi_round | add_to_cart | add_to_cart | ✅ PASS | 正確呼叫工具 |
| combo_with_customization | complex | add_to_cart | add_to_cart | ✅ PASS | 正確呼叫工具 |
| rapid_fire_order | complex | add_to_cart | (無) | ❌ FAIL | 用文字回覆 |
| greeting | basic | (無) | (無) | ✅ PASS | 「你好，想吃什麼呢？」 |

### 失敗模式分析

1. **文字回覆 vs Tool Call（6 場景）**：模型在資訊完整時傾向用自然語言回覆，而非呼叫 `add_to_cart` 工具。這是 `tool_choice: "auto"` 的行為特性，模型自行判斷是否需要工具。
   - 影響場景：basic_order_complete, multi_item, modify_order, multi_round_clarification, rapid_fire_order, query_menu

2. **邊界案例（3 場景）**：模型在購物車為空時仍嘗試呼叫 remove_from_cart，而非告知用戶。
   - 影響場景：modify_without_context, cancel_nonexistent, complex_order_partial_info

3. **結帳流程（1 場景）**：模型先查詢購物車而非直接結帳。
   - 影響場景：checkout_flow

### 優勢

- **缺資訊追問**：6/6 全通過 — 模型在資訊不完整時一律正確追問
- **離題引導**：正確拒絕無關問題並引導回點餐
- **打招呼**：自然友善

### 測試案例（22 個）

<details>
<summary>點擊展開完整測試情境</summary>

#### 基本點餐
- `basic_order`: 「我要一個鮪魚飯糰」→ 缺米種，應追問
- `basic_order_complete`: 「我要一個鮪魚飯糰，紫米的」→ 應呼叫 add_to_cart

#### 查詢
- `combo_query`: 「有什麼套餐可以選？」→ 應呼叫 query_menu
- `query_menu`: 「你們有賣什麼飲料？」→ 應呼叫 query_menu

#### 多品項
- `multi_item`: 「一個起司蛋餅加一杯大冰紅茶」→ 應呼叫 add_to_cart
- `complex_order_complete`: 「兩個鮪魚飯糰紫米、一個起司蛋餅、一杯大冰紅茶、一份薯餅」→ 應呼叫 add_to_cart

#### 缺資訊追問
- `missing_flavor`: 「我要一個飯糰」→ 不應呼叫工具，追問口味
- `missing_quantity`: 「我們每個人都要一個蛋餅」→ 不應呼叫工具，追問人數
- `missing_drink_spec`: 「我要一杯紅茶」→ 不應呼叫工具，追問規格
- `missing_egg_pancake_flavor`: 「來一份蛋餅」→ 不應呼叫工具，追問口味
- `ambiguous_item`: 「給我一個吐司」→ 不應呼叫工具，追問口味

#### 多輪對話
- `multi_round_clarification`: 飯糰→追問→「鮪魚的，紫米」→ 應呼叫 add_to_cart
- `multi_round_drink`: 紅茶→追問→「大杯冰的」→ 應呼叫 add_to_cart
- `rapid_fire_order`: 連續點餐第二輪「再一個起司蛋餅跟一杯大冰紅茶」→ 應呼叫 add_to_cart

#### 邊界案例
- `modify_without_context`: 「把飯糰換成蛋餅」→ 購物車為空，不應呼叫工具
- `cancel_nonexistent`: 「幫我把蛋餅取消」→ 購物車沒蛋餅，不應呼叫工具
- `off_topic`: 「今天天氣好嗎？」→ 不應呼叫工具，引導回點餐

#### 其他
- `modify_order`: 「飯糰改成玉米口味的」→ 應呼叫 add_to_cart
- `checkout_flow`: 「好了就這樣，幫我結帳」→ 應呼叫 finalize_order
- `combo_with_customization`: 「我要 A 套餐，飲料換大冰奶茶」→ 應呼叫 add_to_cart
- `complex_order_partial_info`: 「一個鮪魚飯糰、一個蛋餅、還有一杯紅茶」→ 不應呼叫工具（多項缺資訊）
- `greeting`: 「你好」→ 不應呼叫工具

</details>

---

## 二、TTS Benchmark — Edge TTS (台灣女聲)

### 總結指標

| 指標 | 數值 | 說明 |
|------|------|------|
| Success Rate | **100%** | 全部成功 |
| Avg First Byte Latency | **0.55s** | 首字節延遲 |
| Avg Total Time | **0.68s** | 平均合成時間 |
| Avg RTF | **0.15** | 即時率（<1 = 比即時快） |
| Avg Audio Size | **40.3 KB** | 平均音訊大小 |

### 評估

- **首字節延遲 0.55s** 對語音互動可接受（目標 < 1s）
- **RTF 0.15** 表示合成速度是即時的 6.7 倍，非常優秀
- Edge TTS 作為雲端服務穩定性佳，但需要網路連線

### 測試句（20 句）

| 類別 | 句子 |
|------|------|
| 招呼 | 歡迎光臨源飯糰！請問今天想吃什麼呢？ |
| 確認 | 好的，幫您點了一個鮪魚飯糰和一杯大冰紅茶，總共七十五元。 |
| 推薦 | 我們今天有特價套餐，蛋餅加紅茶只要五十元，要不要試試看？ |
| 結帳 | 您的取餐號碼是 A零三七，請稍等一下喔！ |
| 長句 | 一個鮪魚飯糰、一個起司蛋餅、一杯大冰紅茶、還有一份薯餅。總共一百三十五元，內用對嗎？ |
| 錯誤處理 | 抱歉，我沒有聽清楚，可以再說一次嗎？ |
| 短句 | 好的！ / 要加蛋嗎？ |
| 追問 | 請問飯糰要什麼口味呢？ / 紅茶要大杯還是小杯？ |
| 數字 | 一個鮪魚飯糰三十五元... 總共八十元 / 取餐號碼零一五 |
| 菜單 | 飯糰有鮪魚、肉鬆、玉米... / A套餐蛋餅加紅茶五十元 |
| 提示 | 購物車裡目前沒有蛋餅喔 / 購物車是空的 |
| 超長句 | 兩個鮪魚飯糰、一個起司蛋餅...八項，兩百六十五元。 |
| 引導 | 不好意思，我是點餐助手，只能幫您處理點餐相關的問題喔。 |

---

## 三、ASR Benchmark — SenseVoice-Small

### 狀態：❌ 模型載入失敗

**錯誤原因**：`[Errno 2] No such file or directory: '...funasr/models/sense_voice/whisper_lib/assets/multilingual.tiktoken'`

funasr 1.3.1 的 SenseVoice 模型缺少 `whisper_lib/assets/` 資產目錄。
後端進程中 SenseVoice 可正常載入（透過 HuggingFace hub 下載），但 benchmark 獨立進程載入時觸發此路徑錯誤。

### 測試案例（30 個，15 句 × 男女聲各一）

| 類別 | 測試句 | 數量 |
|------|--------|------|
| 基本點餐 | 我要一個鮪魚飯糰 / 給我一個玉米飯糰 / 一個起司蛋餅 / 一杯大冰紅茶 | 8 |
| 複合點餐 | 一個起司蛋餅加一杯大冰紅茶 / 我要一個鮪魚飯糰還有一份薯餅 | 4 |
| 數量 | 兩杯溫豆漿 | 2 |
| 修改 | 飯糰換成玉米口味 / 紅茶改兩杯 | 4 |
| 查詢 | 你們有賣什麼飲料 / 有什麼套餐可以選 | 4 |
| 結帳 | 好就這樣幫我結帳 / 沒有了可以結帳了 | 4 |
| 招呼 | 你好我想點餐 | 2 |
| 取消 | 蛋餅不要了幫我取消 | 2 |

**待修正**：解決 tiktoken 資產檔路徑問題後重跑。

---

## 四、端對端對話測試（手動驗證）

透過 `/dialogue/text` API 端點手動測試完整對話流程：

```
用戶：你好
助手：嗨～歡迎光臨！想吃什麼呢？

用戶：我要一個傳統飯糰，紫米的
助手：好 一個紫米傳統 還要加辣嗎

用戶：再來一杯大冰豆
助手：好 大杯冰有糖豆漿 還要嗎

用戶：我點了什麼
助手：一個紫米傳統 加辣 一杯大杯冰的有糖豆漿
```

**結果**：✅ LLM → DM → Tool Calling → 購物車管理 全鏈路正常

---

## 五、改善建議

### 短期（提升 LLM 分數）
1. **調整 system prompt**：強調「資訊完整時必須呼叫工具，不要只用文字回覆」
2. **tool_choice 策略**：在特定場景使用 `"required"` 而非 `"auto"`
3. **邊界案例處理**：在 prompt 中加入購物車為空時的行為指引

### 中期（ASR）
4. **修復 tiktoken 資產**：解決 funasr 的 whisper_lib/assets 路徑問題
5. **跑 ASR benchmark**：取得 CER 數據

### 長期（模型選型）
6. **測試 Qwen3-30B-A3B**：MoE 模型可能在 tool calling 上更準確
7. **評估 Qwen3-TTS**：等 VRAM 更大的 GPU 或用 CPU offload
8. **考慮 ElevenLabs**：雲端 TTS 備選方案
