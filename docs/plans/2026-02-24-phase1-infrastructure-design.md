# Phase 1：周邊基礎設施設計

日期：2026-02-24
狀態：approved

---

## 總覽

| # | 任務 | 影響檔案 | 規模 |
|---|------|----------|------|
| 1 | Session TTL + 對話紀錄持久化 | 4-5 個 | 中 |
| 2 | API 限流（slowapi） | 2-3 個 | 小 |
| 3 | CI/CD 強化 | 1 個 | 小 |
| 4 | 購物車品項合併顯示 | 1-2 個 | 中 |
| 5 | 前端測試補齊 | 2 個新建 | 小 |

---

## 任務 1：Session TTL + 對話紀錄持久化

### 目標
1. InMemorySessionStore 加入 TTL 自動過期（防記憶體無限增長）
2. 每段完整對話在 session 結束時寫入 SQLite（供分析/微調用）

### 設計

#### TTL 機制（改 `src/dm/session_store.py`）

- `InMemorySessionStore.__init__` 加入 `self._last_access: Dict[str, float]`
- `get()` 時更新 `_last_access[session_id] = time.time()`
- 新增 `cleanup()` 方法：清除超過 TTL 的 session
  - 過期的 session 先觸發對話紀錄持久化，再清除
- TTL 預設 30 分鐘

#### 對話歷史內嵌 Session

session state 新增 `history` 欄位：

```python
{
    "cart": [],
    "pending_frames": [],
    "last_user_text": None,
    "state": "idle",
    "history": [],       # 新增
    "started_at": None,  # 新增
}
```

每輪對話在 `dialogue_manager.py` 的 `handle()` 中 append：
```python
session["history"].append({
    "role": "user",
    "content": user_text,
    "timestamp": datetime.now().isoformat()
})
# ... 處理後 ...
session["history"].append({
    "role": "assistant",
    "content": response_text,
    "timestamp": datetime.now().isoformat()
})
```

#### 對話紀錄持久化（新建 `src/repository/conversation_log.py`）

SQLite 表 `conversations`：
```sql
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    messages TEXT NOT NULL,      -- JSON: 完整對話歷史
    metadata TEXT,               -- JSON: {items_count, total_amount, completed, turns}
    started_at TEXT,
    ended_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_conversations_session ON conversations(session_id);
CREATE INDEX idx_conversations_ended ON conversations(ended_at);
```

觸發寫入時機：
- 結帳完成（`finalize_order` 工具回傳成功）
- Session TTL 過期（cleanup 時）
- 手動清除 session

#### 查詢 API（新增 endpoint）

`GET /api/conversations` — 需 API Key
- 參數：`date`（日期過濾）、`limit`（預設 50）、`offset`
- 回傳：對話紀錄列表（含 metadata）

`GET /api/conversations/{session_id}` — 需 API Key
- 回傳：單筆完整對話紀錄

#### 背景 Cleanup 任務

在 `app.py` 的 lifespan 中啟動：
```python
async def _session_cleanup_loop():
    while True:
        await asyncio.sleep(300)  # 每 5 分鐘
        _session_store.cleanup()
```

#### Settings 新增

```python
# src/config/settings.py
SESSION_TTL_MINUTES: int = 30
```

#### 影響檔案
- `src/dm/session_store.py` — 加 TTL + cleanup
- `src/config/settings.py` — 加 SESSION_TTL_MINUTES
- `src/repository/conversation_log.py` — 新建
- `src/dm/dialogue_manager.py` — handle() 中記錄 history + 結帳時持久化
- `src/api/app.py` — 背景 cleanup 任務 + 查詢 endpoint

---

## 任務 2：API 限流（slowapi）

### 目標
公開 API 防濫用，保護 LLM/ASR/TTS 高成本資源。

### 設計

#### 安裝依賴
`uv add slowapi`

#### 分層限流策略

| 端點類別 | 限制 | 對應端點 |
|----------|------|----------|
| 語音/對話（高成本） | 10 次/分鐘 per IP | `/dialogue/*`, `/api/voice-chat` |
| 結帳/訂單（寫入） | 5 次/分鐘 per IP | `/api/checkout`, POST `/orders` |
| 查詢（讀取） | 60 次/分鐘 per IP | `/api/menu`, `/cart/*`, GET `/orders/*` |
| 健康檢查 | 不限 | `/healthz` |
| 測試端點 | 30 次/分鐘 per IP | `/llm/test`, `/asr/test`, `/tts/*` |

#### 實作方式

```python
# app.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 各 route 加裝飾器
@app.post("/dialogue/text")
@limiter.limit("10/minute")
async def dialogue_text(request: Request, ...):
    ...
```

#### Settings 新增

```python
# src/config/settings.py
RATE_LIMIT_DIALOGUE: str = "10/minute"
RATE_LIMIT_CHECKOUT: str = "5/minute"
RATE_LIMIT_QUERY: str = "60/minute"
RATE_LIMIT_TEST: str = "30/minute"
```

#### 影響檔案
- `src/api/app.py` — limiter 初始化 + route 裝飾器
- `src/api/voice_router.py` — voice-chat route 裝飾器
- `src/config/settings.py` — 限流參數
- `pyproject.toml` — 加 slowapi 依賴

---

## 任務 3：CI/CD 強化

### 目標
補齊前端測試 + 程式碼品質檢查，全部 push/PR 自動執行。

### 設計

#### 修改 `.github/workflows/tests.yml`

兩個平行 job：

**Job 1: backend**
```yaml
- uv sync --all-extras --locked
- uv run ruff check src/
- uv run pytest -q --strict-markers
```

**Job 2: frontend**
```yaml
- npm ci --prefix src/frontend_next
- npm run test --prefix src/frontend_next -- --run
```

注意：mypy 先不加（目前 codebase 沒有完整 type annotation，加了會一堆 error）。
等 Phase 2 或之後有時間再補 type annotation + mypy。

#### 影響檔案
- `.github/workflows/tests.yml`

---

## 任務 4：購物車品項合併顯示

### 目標
同品項+同客製自動合併顯示 `品項 x數量 — $小計`。

### 設計

#### 合併邏輯

新增 `_item_key(frame: Dict) -> str`：
```python
def _item_key(frame):
    """提取品項唯一身份，用於合併判斷"""
    rtype = frame.get("recognized_type", "")
    name = format_item(frame)  # 已包含客製選項
    return f"{rtype}:{name}"
```

用 `format_item()` 的輸出作為 key — 因為它已經把所有客製選項都編碼在字串裡了。
同名 = 同品項 + 同客製。

#### 修改 `get_order_summary()` 和 `get_short_summary()`

```python
from collections import Counter, OrderedDict

def get_order_summary(cart):
    if not cart:
        return "目前沒有品項"

    # 合併同品項
    groups = OrderedDict()  # 保持插入順序
    for item in cart:
        key = _item_key(item)
        if key not in groups:
            groups[key] = {"item": item, "count": 0, "subtotal": 0}
        groups[key]["count"] += 1
        pi = get_price_info(item.get("item_name", ""))
        groups[key]["subtotal"] += extract_total(pi, 1)

    # 格式化
    lines = []
    total_count = 0
    total_price = 0
    for g in groups.values():
        name = format_item(g["item"])
        if g["count"] > 1:
            lines.append(f"{name} x{g['count']}")
        else:
            lines.append(name)
        total_count += g["count"]
        total_price += g["subtotal"]

    items_str = ", ".join(lines)
    return f"這樣一共{items_str}，共 {total_count} 個品項，共 {total_price}元"
```

#### 重要：資料結構不變
- 購物車仍然是 `List[Dict]`，每個品項獨立存在
- 只改顯示層（summary 輸出），不影響刪除/修改操作
- 刪除仍按 index 操作，不受影響

#### 影響檔案
- `src/dm/cart_manager.py` — `_item_key()` + 修改 summary 函數

---

## 任務 5：前端測試補齊

### 目標
補齊 AudioVisualizer + MenuDisplay 的 Vitest + RTL 測試。

### 設計

#### `__tests__/components/AudioVisualizer.test.tsx`

測試項目：
- 渲染 4 種狀態（idle / listening / processing / speaking）不報錯
- props 傳入 audioLevel 正確反映
- canvas context mock（jsdom 不支援 canvas，需 mock getContext）
- 元件 unmount 不報錯（cleanup animation frame）

#### `__tests__/components/MenuDisplay.test.tsx`

測試項目：
- 菜單分類正確渲染（11 分類）
- Accordion 展開/收合互動
- 圖片載入失敗時 fallback 顯示
- 空菜單時的 fallback UI

#### 影響檔案
- `src/frontend_next/__tests__/components/AudioVisualizer.test.tsx` — 新建
- `src/frontend_next/__tests__/components/MenuDisplay.test.tsx` — 新建

---

## 驗證方式

每個任務完成後：
1. 後端：`uv run python -m pytest tests/ -x -q`（124+ tests pass）
2. 前端：`npm run test --prefix src/frontend_next`（47+ tests pass）
3. 新功能需有對應測試
