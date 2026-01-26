# LLM 功能使用指南

## 快速開始

### 您的 LM Studio 配置
```
地址：http://127.0.0.1:1234
模型：qwen2.5-14b-instruct-1m
狀態：✅ 已驗證正常運作
```

## 方式 1：預設配置（推薦 - LLM 禁用）

```python
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore

# 簡單初始化（LLM 預設禁用 - 最安全）
dm = DialogueManager(store=InMemorySessionStore())

# 使用對話
response = dm.handle("session_001", "我要飯糰")
```

**優勢：**
- 無需 LLM 依賴
- 快速響應（< 10ms）
- 100% 可靠

---

## 方式 2：啟用 LLM 功能

```python
from src.dm.dialogue_manager import DialogueManager
from src.dm.llm_router import LLMRouter
from src.dm.llm_clarifier import LLMClarifier
from src.services.llm_tool_caller import LLMToolCaller
from src.dm.session_store import InMemorySessionStore

# 1. 初始化 LLM Tool Caller
llm = LLMToolCaller(
    base_url="http://127.0.0.1:1234/v1/chat/completions",
    model="qwen2.5-14b-instruct-1m",
    timeout=30
)

# 2. 初始化 LLM Router
router = LLMRouter(llm, timeout=10, confidence_threshold=0.75)

# 3. 初始化 LLM Clarifier
clarifier = LLMClarifier(llm)

# 4. 建立 Dialogue Manager（LLM 啟用）
dm = DialogueManager(
    store=InMemorySessionStore(),
    llm_router=router,
    llm_clarifier=clarifier,
    llm_enabled=True
)

# 5. 使用對話
response = dm.handle("session_001", "我要飯糰")
```

**功能：**
- 使用 LLM 分類未知項目
- 生成自然澄清問題
- 自動備選至硬編碼問題

---

## 工作流程

### 訂單路由流程
```
用戶輸入
  ↓
關鍵詞路由器 [< 10ms]
  ├─ 匹配找到 → 使用
  └─ 無匹配 → LLM 分類 [500-2000ms]
     ├─ 信心度 > 0.75 → 使用
     └─ 信心度 ≤ 0.75 → 返回「不明白」
```

### 澄清問題流程
```
檢測到缺失信息
  ↓
LLM 生成自然問題 [300-800ms]
  ├─ 成功 → 返回自然問題
  └─ 失敗 → 備選至硬編碼問題 [< 1ms]
```

---

## 配置參數

### LLMRouter
```python
router = LLMRouter(
    llm=llm,                        # LLMToolCaller 實例
    timeout=10,                     # 分類超時（秒）
    confidence_threshold=0.75       # 信心度閾值
)
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| timeout | 10 | LLM 調用超時（秒） |
| confidence_threshold | 0.75 | 信心度閾值（0-1） |

### LLMClarifier
```python
clarifier = LLMClarifier(llm=llm)
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| llm | - | LLMToolCaller 實例 |

### DialogueManager
```python
dm = DialogueManager(
    store=store,                    # 會話存儲
    llm_router=router,              # LLM 路由器（可選）
    llm_clarifier=clarifier,        # LLM 澄清器（可選）
    llm_enabled=False               # 功能開關（預設關閉）
)
```

---

## 性能指標

| 操作 | 耗時 | 備註 |
|------|------|------|
| 關鍵詞路由 | < 10ms | 無變化 |
| LLM 分類（快取） | < 1ms | 極快 |
| LLM 分類（新調用） | 500-2000ms | 僅未知項目 |
| LLM 澄清（快取） | < 1ms | 極快 |
| LLM 澄清（新調用） | 300-800ms | 可接受 |

---

## 信心度評分

```
信心度范圍    判斷      行動
0.85 - 1.0   非常高    使用 LLM 路由
0.75 - 0.84  高        使用 LLM 路由
< 0.75       低/中等   備選至硬編碼或返回「不明白」
```

---

## 錯誤處理

### LLM 路由失敗時
```python
# 自動備選至硬編碼路由
result = router.classify("xyz")
# 若信心度低或調用失敗，返回 route_type = "unknown"
```

### LLM 澄清失敗時
```python
# 自動備選至硬編碼問題
question = clarifier.generate_question("riceball", ["flavor"])
# 若 LLM 失敗，返回: "想要哪個口味的飯糰？"
```

---

## 快取機制

### 自動快取
```python
# 首次調用
result = router.classify("我要飯糰")  # 500-2000ms

# 後續相同調用（快取命中）
result = router.classify("我要飯糰")  # < 1ms
```

### 手動清除快取
```python
# 清除路由器快取
router.clear_cache()

# 清除澄清器快取
clarifier.clear_cache()
```

---

## 監控和調試

### 檢查 LLM 是否啟用
```python
if dm.llm_router is not None:
    print("LLM 路由器已啟用")

if dm.llm_clarifier is not None:
    print("LLM 澄清器已啟用")
```

### 查看分類結果
```python
result = router.classify("某個輸入")
print(f"路由類型：{result['route_type']}")
print(f"信心度：{result['confidence']}")
print(f"理由：{result['reasoning']}")
print(f"備選：{result['alternatives']}")
```

---

## 最佳實踐

### ✅ 推薦做法
1. 預設使用 `llm_enabled=False`（最安全）
2. 監控 1-2 週後再考慮啟用
3. 設置信心度閾值為 0.75 或更高
4. 定期清除快取（每日或每週）
5. 監控 LLM 響應時間

### ❌ 避免做法
1. 不要設置信心度閾值太低（< 0.5）
2. 不要頻繁清除快取（會影響性能）
3. 不要設置超時太短（< 5 秒）
4. 不要在高負載時啟用 LLM

---

## 常見問題

### Q: 可以同時使用多個 LLM 服務嗎？
A: 可以，只需創建多個 LLMToolCaller 實例，分別連接到不同的 LM Studio 服務器。

### Q: 如何調整信心度閾值？
A: 在初始化 LLMRouter 時設置：
```python
router = LLMRouter(llm, confidence_threshold=0.8)  # 更高的閾值
```

### Q: LLM 響應慢怎麼辦？
A: 檢查以下項目：
1. LM Studio 服務器是否正常運行
2. 增加超時時間：`timeout=60`
3. 檢查網絡連接
4. 檢查 LM Studio 的 GPU 使用

### Q: 如何禁用 LLM？
A: 設置 `llm_enabled=False` 或不傳入 llm_router/llm_clarifier 參數。

---

## 技術支持

如有問題，請檢查：
1. LM Studio 是否運行：`curl http://127.0.0.1:1234/v1/models`
2. 模型是否加載：檢查 LM Studio UI
3. 日誌文件：查看應用日誌
4. 測試覆蓋：執行 `pytest tests/test_llm_*.py -v`

---

## 版本信息

- Phase 1 實現：保守混合模式
- LLM 型號：qwen2.5-14b-instruct-1m
- 測試覆蓋：127 個測試（全部通過）
- 相容性：100% 向後兼容

