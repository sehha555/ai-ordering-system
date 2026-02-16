# 系統全面優化設計

**日期：** 2026-02-16
**狀態：** 已完成

## 背景

端對端系統測試發現兩個 bug 和一個架構弱點：
1. `voice_router.py` 呼叫不存在的私有方法，導致訂單 total = 0
2. LLM tool call 解析只依賴 `msg.tool_calls`，Qwen 模型 fallback 到 content 時丟失
3. 跨模組呼叫私有方法的 code smell

## 變更內容

### 1. Regex Fallback Parser（llm_tool_caller.py）

在 `pick_first_tool_call()` 中新增 fallback 路徑：
- 先檢查 `msg.tool_calls`（OpenAI 標準）
- 若為空，用 regex 從 `msg.content` 提取 `{"name": "...", "arguments": {...}}`
- 提取成功後清理 content 中的 raw tool call 文字
- 構造成 OpenAI 格式的 tool_call 物件回傳

### 2. 方法重命名（4 個檔案）

| 舊名稱 | 新名稱 |
|---|---|
| `_get_price_info()` | `get_price_info()` |
| `_extract_total_from_pi()` | `extract_total()` |

影響檔案：
- `src/dm/dialogue_manager.py` — 方法定義 + 內部呼叫
- `src/api/app.py` — 結帳端點呼叫
- `src/api/voice_router.py` — 語音路由呼叫（同時修正方法名錯誤）
- `src/dm/tool_registry.py` — 工具購物車摘要呼叫

### 3. rice 參數調查

初始嘗試在 `get_price_info()` 中為飯糰查價補上 `rice` 參數，但 `quote_riceball_price()` 不接受此參數（rice 不影響價格計算），已移除。

## 測試結果

- 後端 pytest：124 passed
- 前端 vitest：37 passed
