# 真串流 Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 讓 `run_turn_stream` 從第一個 token 開始真正串流輸出，文字回覆直接 yield 給 TTS，不等完整回應。

**Architecture:** 新增 `call_llm_stream_with_tool_detection()` method，用狀態機即時辨別回應是 tool call 還是文字：文字 token 立即 yield（→ TTS 即時播放）；tool call token 則 buffer 直到 JSON 完整後執行。`run_turn_stream()` 改為使用此 method 取代目前的 `call_llm_async()`，消除假串流（按標點切完整文字）。

**Tech Stack:** Python asyncio + httpx（已引入）、Qwen3 `<tool_call>` 格式 + OpenAI tool_calls delta 格式雙路支援

---

## 背景：現在哪裡慢？

### 現況流程（`run_turn_stream`，`llm_tool_caller.py:322`）

```
loop iteration:
  call_llm_async()         ← 等完整回應（2-3.5s）
  if tool_call:
    execute_tool()
    continue loop
  else:
    # Phase 2：按標點假切割完整 full_text 逐段 yield（假串流）
    for ch in full_text:
      if ch in PUNCTS: yield text_delta
```

問題：
1. **Phase 1 每輪等完整回應**：即使只有一個 tool call，也要等 LLM 生成完整 JSON（含結束標記）才知道
2. **Phase 2 是假串流**：`full_text` 在 `call_llm_async()` 完成時就已完整，假裝一個字一個字 yield，實際延遲零改善
3. **文字回覆場景**（追問、無 tool call 的對話）：浪費一次完整 LLM round trip

### 目標流程

```
call_llm_stream_with_tool_detection():
  stream tokens:
    if first token = "<tool_call>" or tool_calls delta:
      → BUFFER mode: 累積直到 JSON 完整
      → yield {"type": "tool_call", ...}
    else:
      → TEXT mode: 每個 token 立即 yield {"type": "text_token", ...}
```

**效益：**
- 文字回覆（追問、簡單回答）：TTFA 從 ~2s → ~100ms（LLM 第一個 token 時間）
- tool call 回覆：Phase 1 每輪耗時不變，但文字最終回覆仍受益
- 消除假串流的 CPU 切割延遲

---

## 關鍵設計決策

### Qwen3 tool call 偵測（streaming）

LM Studio + Qwen3 有兩種格式：

**格式 A：OpenAI 標準 tool_calls delta**
```json
{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_x","function":{"name":"add_to_cart","arguments":""}}]}}]}
{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"item\""}}]}}]}
...
{"choices":[{"finish_reason":"tool_calls"}]}
```

**格式 B：Qwen 原生 `<tool_call>` 在 content（text mode）**
```json
{"choices":[{"delta":{"content":"<tool_call>\n{\"name\":\"add_to_cart\","}}]}
{"choices":[{"delta":{"content":"\"arguments\":{...}}"}}]}
{"choices":[{"delta":{"content":"\n</tool_call>"}}]}
```

**格式 C：純文字回覆**
```json
{"choices":[{"delta":{"content":"好的"}}]}
{"choices":[{"delta":{"content":"，"}}]}
```

**偵測邏輯（前幾個 token 即可判斷）：**
```
if delta.tool_calls → TOOL_CALL_OPENAI mode
elif delta.content starts with "<tool_call>" → TOOL_CALL_QWEN mode
elif delta.content is regular text → TEXT mode → yield immediately
```

---

## Task 1：新增 `call_llm_stream_with_tool_detection()`

**Files:**
- Modify: `src/services/llm_tool_caller.py`（在 `call_llm_stream` 之後，約 line 320 插入）
- Test: `tests/services/test_llm_stream_detection.py`（新建）

### Step 1：先讀懂現有 streaming 方法

Read `src/services/llm_tool_caller.py:288-320`（`call_llm_stream`）。確認 httpx 的 `client.stream` 用法。

### Step 2：寫失敗測試

建立 `tests/services/test_llm_stream_detection.py`：

```python
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.llm_tool_caller import LLMToolCaller


def _make_sse_line(delta: dict, finish_reason=None) -> str:
    chunk = {"choices": [{"delta": delta, "finish_reason": finish_reason}]}
    return f"data: {json.dumps(chunk)}\n"


async def _mock_stream_lines(lines: list[str]):
    """模擬 httpx aiter_lines()"""
    for line in lines:
        yield line


@pytest.fixture
def caller():
    return LLMToolCaller(base_url="http://localhost:1234/v1/chat/completions")


@pytest.mark.asyncio
async def test_text_response_yields_text_tokens(caller):
    """純文字回覆：每個 token 立即 yield"""
    lines = [
        _make_sse_line({"role": "assistant", "content": "好"}),
        _make_sse_line({"content": "的"}),
        _make_sse_line({"content": "，還需要什麼？"}, finish_reason="stop"),
        "data: [DONE]\n",
    ]
    events = []
    with patch.object(caller, '_stream_lines', return_value=_mock_stream_lines(lines)):
        async for evt in caller.call_llm_stream_with_tool_detection(messages=[]):
            events.append(evt)

    text_events = [e for e in events if e["type"] == "text_token"]
    assert text_events[0]["content"] == "好"
    assert text_events[1]["content"] == "的"
    finish = [e for e in events if e["type"] == "finish"]
    assert finish[0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_openai_tool_call_yields_tool_call_event(caller):
    """OpenAI tool_calls delta 格式：buffer 並 yield tool_call"""
    lines = [
        _make_sse_line({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "add_to_cart", "arguments": ""}}]}),
        _make_sse_line({"tool_calls": [{"index": 0, "function": {"arguments": '{"item_type": "rice_ball"}'}}]}),
        _make_sse_line({}, finish_reason="tool_calls"),
        "data: [DONE]\n",
    ]
    events = []
    with patch.object(caller, '_stream_lines', return_value=_mock_stream_lines(lines)):
        async for evt in caller.call_llm_stream_with_tool_detection(messages=[], tools_schema=[]):
            events.append(evt)

    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_events) == 1
    tc = tool_events[0]["tool_call"]
    assert tc["function"]["name"] == "add_to_cart"
    assert '"item_type"' in tc["function"]["arguments"]
    # 沒有 text_token
    assert not any(e["type"] == "text_token" for e in events)


@pytest.mark.asyncio
async def test_qwen_tool_call_format_yields_tool_call_event(caller):
    """Qwen <tool_call> content 格式：buffer 並解析"""
    tool_json = '{"name": "add_to_cart", "arguments": {"item_type": "rice_ball"}}'
    lines = [
        _make_sse_line({"role": "assistant", "content": f"<tool_call>\n{tool_json}\n</tool_call>"}),
        _make_sse_line({}, finish_reason="stop"),
        "data: [DONE]\n",
    ]
    events = []
    with patch.object(caller, '_stream_lines', return_value=_mock_stream_lines(lines)):
        async for evt in caller.call_llm_stream_with_tool_detection(messages=[], tools_schema=[]):
            events.append(evt)

    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0]["tool_call"]["function"]["name"] == "add_to_cart"


@pytest.mark.asyncio
async def test_empty_response_yields_finish(caller):
    """空回應：只 yield finish"""
    lines = [
        _make_sse_line({}, finish_reason="stop"),
        "data: [DONE]\n",
    ]
    events = []
    with patch.object(caller, '_stream_lines', return_value=_mock_stream_lines(lines)):
        async for evt in caller.call_llm_stream_with_tool_detection(messages=[]):
            events.append(evt)

    assert events[-1]["type"] == "finish"
    assert not any(e["type"] == "text_token" for e in events)
    assert not any(e["type"] == "tool_call" for e in events)
```

### Step 3：跑測試確認失敗

```bash
cd C:\Users\User\Desktop\ai-ordering-system
uv run pytest tests/services/test_llm_stream_detection.py -v
```

Expected: `AttributeError: 'LLMToolCaller' object has no attribute '_stream_lines'` 或類似

### Step 4：實作 `_stream_lines` 和 `call_llm_stream_with_tool_detection`

在 `src/services/llm_tool_caller.py` 的 `call_llm_stream` 之後插入：

```python
async def _stream_lines(
    self,
    messages: List[Dict[str, Any]],
    tools_schema: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.0,
):
    """底層：送 streaming 請求並 yield 每行。抽成 method 方便測試 mock。"""
    payload: Dict[str, Any] = {
        "model": self.model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if tools_schema:
        payload["tools"] = tools_schema
    async with httpx.AsyncClient(timeout=self.timeout) as client:
        async with client.stream("POST", self.base_url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                yield line

async def call_llm_stream_with_tool_detection(
    self,
    *,
    messages: List[Dict[str, Any]],
    tools_schema: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.0,
) -> AsyncIterator[Dict[str, Any]]:
    """
    串流 LLM 請求，即時辨別 tool call vs 文字。

    Yields:
      {"type": "text_token", "content": "..."}   # 文字 token，立即 yield
      {"type": "tool_call",  "tool_call": {...}}  # 完整 tool call（buffer 後送）
      {"type": "finish",     "finish_reason": "..."} # 串流結束
    """
    # State: "detecting" → "text" | "tool_openai" | "tool_qwen"
    mode = "detecting"
    tool_call_chunks: Dict[int, Dict[str, Any]] = {}  # OpenAI: index → accumulated call
    qwen_buf = ""  # Qwen: accumulated <tool_call> content

    async for line in self._stream_lines(messages, tools_schema, temperature):
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        # 偵測模式
        if mode == "detecting":
            if delta.get("tool_calls"):
                mode = "tool_openai"
            elif delta.get("content"):
                content: str = delta["content"]
                if content.lstrip().startswith("<tool_call"):
                    mode = "tool_qwen"
                    qwen_buf = content
                    continue
                else:
                    mode = "text"
                    yield {"type": "text_token", "content": content}
                    continue
            else:
                continue  # role-only delta

        # 文字模式：立即 yield
        if mode == "text":
            if delta.get("content"):
                yield {"type": "text_token", "content": delta["content"]}

        # OpenAI tool_calls 累積
        elif mode == "tool_openai":
            for tc_delta in (delta.get("tool_calls") or []):
                idx = tc_delta.get("index", 0)
                if idx not in tool_call_chunks:
                    tool_call_chunks[idx] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = tool_call_chunks[idx]
                if tc_delta.get("id"):
                    tc["id"] = tc_delta["id"]
                fn = tc_delta.get("function") or {}
                tc["function"]["name"] += fn.get("name") or ""
                tc["function"]["arguments"] += fn.get("arguments") or ""

        # Qwen <tool_call> 累積
        elif mode == "tool_qwen":
            if delta.get("content"):
                qwen_buf += delta["content"]

    # 串流結束後輸出 tool call
    if mode == "tool_openai" and tool_call_chunks:
        tc = tool_call_chunks[min(tool_call_chunks)]
        if not tc["id"]:
            tc["id"] = "stream_toolcall_0"
        yield {"type": "tool_call", "tool_call": tc}

    elif mode == "tool_qwen" and qwen_buf:
        match = _TOOL_CALL_RE.search(qwen_buf)
        if match:
            try:
                raw = json.loads(match.group(1))
                name = raw.get("name", "")
                arguments = raw.get("arguments", {})
                yield {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "qwen_toolcall_0",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    },
                }
            except (json.JSONDecodeError, TypeError):
                logger.warning("[LLM] Qwen tool_call JSON 解析失敗: {}", qwen_buf[:200])

    yield {"type": "finish", "finish_reason": "stop"}
```

### Step 5：跑測試確認通過

```bash
uv run pytest tests/services/test_llm_stream_detection.py -v
```

Expected: 4 tests PASS

### Step 6：ruff check

```bash
uv run ruff check src/services/llm_tool_caller.py
```

Expected: All checks passed

### Step 7：commit

```bash
git add src/services/llm_tool_caller.py tests/services/test_llm_stream_detection.py
git commit -m "feat: 新增 call_llm_stream_with_tool_detection 真串流 tool 偵測"
```

---

## Task 2：重構 `run_turn_stream` 使用真串流

**Files:**
- Modify: `src/services/llm_tool_caller.py`（`run_turn_stream`，line 322-441）
- Test: `tests/services/test_llm_stream_detection.py`（擴充）

### Step 1：補充 `run_turn_stream` 整合測試

在 `test_llm_stream_detection.py` 新增：

```python
@pytest.mark.asyncio
async def test_run_turn_stream_text_only_true_streaming(caller):
    """文字回覆：text_delta 按 token 順序 yield，不假串流"""
    # 模擬：LLM 直接回文字（無 tool call）
    text_lines = [
        _make_sse_line({"role": "assistant", "content": "好的"}),
        _make_sse_line({"content": "，"}),
        _make_sse_line({"content": "還需要什麼嗎？"}, finish_reason="stop"),
        "data: [DONE]\n",
    ]
    with patch.object(caller, '_stream_lines', return_value=_mock_stream_lines(text_lines)):
        events = []
        async for evt in caller.run_turn_stream(
            system_prompt="test",
            user_text="你好",
            history=[],
            tools_schema=[],
            tool_map={},
            allowed_args={},
        ):
            events.append(evt)

    text_deltas = [e for e in events if e["type"] == "text_delta"]
    assert text_deltas[0]["content"] == "好的"
    assert text_deltas[1]["content"] == "，"
    assert text_deltas[2]["content"] == "還需要什麼嗎？"

    done = [e for e in events if e["type"] == "done"]
    assert done[0]["assistant_text"] == "好的，還需要什麼嗎？"


@pytest.mark.asyncio
async def test_run_turn_stream_tool_call_then_text(caller):
    """一次 tool call 後文字回覆：tool_call event + text_delta"""
    tool_lines = [
        _make_sse_line({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "add_to_cart", "arguments": '{"item_type":"rice_ball"}'}}]}),
        _make_sse_line({}, finish_reason="tool_calls"),
        "data: [DONE]\n",
    ]
    text_lines = [
        _make_sse_line({"content": "已加入購物車！"}),
        _make_sse_line({}, finish_reason="stop"),
        "data: [DONE]\n",
    ]
    call_count = 0
    async def mock_stream_lines_sequence(*args, **kwargs):
        nonlocal call_count
        lines = tool_lines if call_count == 0 else text_lines
        call_count += 1
        for line in lines:
            yield line

    def fake_tool(**kwargs):
        return {"ok": True, "result": {"message": "已加入！"}}

    with patch.object(caller, '_stream_lines', side_effect=mock_stream_lines_sequence):
        events = []
        async for evt in caller.run_turn_stream(
            system_prompt="test",
            user_text="加一個紫米飯糰",
            history=[],
            tools_schema=[{}],
            tool_map={"add_to_cart": fake_tool},
            allowed_args={"add_to_cart": {"item_type"}},
        ):
            events.append(evt)

    assert any(e["type"] == "tool_call" for e in events)
    assert any(e["type"] == "text_delta" for e in events)
    done = [e for e in events if e["type"] == "done"]
    assert done[0]["assistant_text"] == "已加入購物車！"
```

### Step 2：跑新測試確認失敗

```bash
uv run pytest tests/services/test_llm_stream_detection.py::test_run_turn_stream_text_only_true_streaming -v
uv run pytest tests/services/test_llm_stream_detection.py::test_run_turn_stream_tool_call_then_text -v
```

Expected: FAIL（`run_turn_stream` 仍用 `call_llm_async`）

### Step 3：重構 `run_turn_stream`

**重要注意事項（讀完再動手）：**
1. `PerfTimer("llm_api_call")` context manager 要保留計時邏輯，改為手動 `start = time.perf_counter()` + `elapsed = time.perf_counter() - start`
2. `early_tts` 邏輯保留（`_EARLY_TTS_TOOLS` set，照舊）
3. `accumulated_text` 要在 text_token loop 中累積，供 `done` event 的 `assistant_text` 使用

```python
async def run_turn_stream(
    self,
    *,
    system_prompt: str,
    user_text: str,
    history: List[Dict[str, Any]],
    tools_schema: List[Dict[str, Any]],
    tool_map: Dict[str, Callable[..., Dict[str, Any]]],
    allowed_args: Dict[str, set],
    context: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    真串流版 run_turn：
    - Phase 1 tool call 偵測 + Phase 2 文字回覆 全程串流
    - 文字 token 立即 yield（不等完整回應）
    - tool call buffer 後執行，繼續迴圈
    """
    logger.info("[LLM] 開始 run_turn_stream (真串流): '{}'", user_text)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _NO_THINK_PREFIX + system_prompt}
    ]
    messages.extend(_PRIMING_MESSAGES)
    messages.extend(history)
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": user_text})

    last_tool_trace: List[Dict[str, Any]] = []

    for step in range(self.max_steps):
        llm_start = time.perf_counter()
        mode = None          # "text" | "tool_call" | None（空回應）
        pending_tool_call = None
        accumulated_text = ""

        async for event in self.call_llm_stream_with_tool_detection(
            messages=messages,
            tools_schema=tools_schema,
            temperature=0.0,
        ):
            evt_type = event["type"]

            if evt_type == "text_token":
                mode = "text"
                content = event["content"]
                accumulated_text += content
                yield {"type": "text_delta", "content": content}  # 真串流！

            elif evt_type == "tool_call":
                mode = "tool_call"
                pending_tool_call = event["tool_call"]

            elif evt_type == "finish":
                llm_elapsed = time.perf_counter() - llm_start
                logger.info("[PERF] llm_stream 耗時 {:.3f}s (step {})", llm_elapsed, step)

        # 根據 mode 決定後續動作
        if mode == "text":
            new_history = history + [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": accumulated_text},
            ]
            yield {
                "type": "done",
                "assistant_text": accumulated_text,
                "history": new_history,
                "tool_trace": last_tool_trace,
            }
            return

        elif mode == "tool_call" and pending_tool_call:
            tool_call = pending_tool_call

            # 把 assistant 的 tool_call 記到 messages
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call],
            })

            # 執行 tool
            exec_result = self.execute_tool_call(
                tool_call,
                tool_map=tool_map,
                allowed_args=allowed_args,
            )
            tool_name = tool_call.get("function", {}).get("name", "")
            logger.info("[LLM] tool_call: {} → ok={}", tool_name, exec_result.get("ok"))
            last_tool_trace.append({"tool_call": tool_call, "exec": exec_result})

            yield {"type": "tool_call", "tool_call": tool_call, "exec": exec_result}

            # Early TTS（add/remove 成功後立即播報工具回傳的 message）
            if tool_name in _EARLY_TTS_TOOLS and exec_result.get("ok"):
                tool_result = exec_result.get("result")
                tool_msg = (
                    tool_result.get("message", "") if isinstance(tool_result, dict) else ""
                )
                if tool_msg:
                    yield {"type": "early_tts", "content": tool_msg}

            # 把 tool result 回灌給模型
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", "toolcall_0"),
                "content": json.dumps(exec_result, ensure_ascii=False),
            })
            # 繼續下一輪

        else:
            # 空回應
            fallback = "抱歉，請再說一次"
            yield {"type": "text_delta", "content": fallback}
            yield {
                "type": "done",
                "assistant_text": fallback,
                "history": history,
                "tool_trace": last_tool_trace,
            }
            return

    # 超過最大步數
    logger.warning("[LLM] run_turn_stream 超過最大步數 {}", self.max_steps)
    fallback = "抱歉，處理您的請求時發生問題，請再說一次"
    yield {"type": "text_delta", "content": fallback}
    yield {
        "type": "done",
        "assistant_text": fallback,
        "error": "max_steps_exceeded",
        "history": history,
        "tool_trace": last_tool_trace,
    }
```

### Step 4：跑所有測試

```bash
uv run pytest tests/services/test_llm_stream_detection.py -v
```

Expected: 全部 6 tests PASS

### Step 5：跑全套測試確認沒有 regression

```bash
uv run pytest --tb=short -q
```

Expected: All pass（舊 270 tests + 新 6 tests）

### Step 6：ruff check

```bash
uv run ruff check src/services/llm_tool_caller.py
```

### Step 7：commit

```bash
git add src/services/llm_tool_caller.py tests/services/test_llm_stream_detection.py
git commit -m "feat: run_turn_stream 改用真串流，文字 token 即時 yield"
```

---

## Task 3：清除舊 `call_llm_stream`（若無其他使用者）

**Files:**
- Modify: `src/services/llm_tool_caller.py`

### Step 1：確認是否有其他使用

```bash
grep -rn "call_llm_stream" src/ tests/
```

Expected output（確認只有定義和 `_stream_lines` 內部）：無外部呼叫

### Step 2：若無外部使用，刪除

刪除 `llm_tool_caller.py` 的 `call_llm_stream` method（line 288-320）。

若有外部使用：跳過此 Task，在 Task 4 備注。

### Step 3：跑測試確認

```bash
uv run pytest --tb=short -q
```

### Step 4：commit

```bash
git add src/services/llm_tool_caller.py
git commit -m "refactor: 移除已無使用的 call_llm_stream（由 call_llm_stream_with_tool_detection 取代）"
```

---

## Task 4：手動 E2E 驗測

這個 task 需要後端 + LM Studio 實際運行，無法用 unit test 覆蓋。

### Step 1：啟動 LM Studio

確認 Qwen3-30B-A3B 已載入，端點 `http://127.0.0.1:1234/v1/chat/completions`。

### Step 2：啟動後端

```bash
cd C:\Users\User\Desktop\ai-ordering-system
uv run uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

### Step 3：啟動前端

```bash
cd src/frontend_next
npm run dev
```

### Step 4：驗測場景

| 場景 | 預期行為 | 驗測方式 |
|------|---------|---------|
| 說「你好」（無 tool call） | 第一個 token 立即有 TTS 音訊（TTFA ~100-300ms） | 聽聲音 + 看 log `[PERF] TTFA` |
| 說「加一個紫米飯糰」（有 tool call） | 先聽到「已加入購物車」(early_tts)，購物車更新 | 聽聲音 + 看購物車 |
| 說「這樣就好嗎？」（追問場景，文字回覆） | TTFA 明顯比以前快 | log 對比 |

### Step 5：查看 PERF log

```bash
grep "PERF" logs/  # 或直接看 console
```

預期：`[PERF] TTFA` 時間比重構前（~2-3s）大幅縮短（~0.1-0.5s for 文字回覆）

---

## 風險與 Rollback

| 風險 | 機率 | 應對 |
|------|------|------|
| LM Studio streaming + tools 回傳格式不一致 | 中 | `_TOOL_CALL_RE` fallback 已在 Qwen mode 保留，觀察 log `[LLM] Qwen tool_call JSON 解析失敗` |
| tool call 的 arguments streaming 分割不完整（JSON 不合法） | 低 | OpenAI mode 完整 buffer 後才解析；Qwen mode 同樣 buffer 完整 `</tool_call>` 後才解析 |
| 效能無改善（LM Studio TTFT 本身就慢） | 低 | 改善的是 Phase 2 假串流延遲，TTFT 取決於 LLM，Phase 2 改善是確定的 |

Rollback：`git revert` Task 2 的 commit，`run_turn_stream` 回到原版。Task 1 的新 method 無害，可保留。

---

## 預期改善量

| 場景 | 改善前 | 改善後 | 說明 |
|------|--------|--------|------|
| 純文字回覆（追問、閒聊） | TTFA ~2-3s | TTFA ~0.1-0.5s | 第一個 token 即送 TTS |
| 單次 tool call + 文字回覆 | TTFA ~4-5s | TTFA ~2.5-3.5s + 文字串流 | tool call 等待不變，文字部分改善 |
| 多次 tool call | 無改善（tool call 需 buffer） | 同左 | 架構限制，Phase 1 串流對多 tool call 無助益 |
