# Code Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the critical/high issues found in the 2026-02-08 code review of the frontend-backend integration (Parts 1-5).

**Architecture:** Minimal targeted fixes — remove debug code, secure the checkout endpoint by dropping API Key requirement (proxy-only access), add empty cart guard, fix order number race condition with SQLite transaction, and remove dead code.

**Tech Stack:** FastAPI, SQLite, Next.js (React 19), Zustand, Tailwind v4

---

## Issues Addressed (by priority)

| # | Severity | Issue | Task |
|---|----------|-------|------|
| 3 | Critical | Debug file written to desktop in `/dialogue/voice` | 1 |
| 1 | Critical | API Key hardcoded in `CheckoutFlow.tsx` | 2 |
| 6 | High | Inconsistent auth policy between endpoints | 2 |
| 5 | High | No empty cart check on checkout | 3 |
| 2 | Critical | Race condition on order number generation | 4 |
| 8 | Medium | Dead code in `get_next_order_number` | 4 |
| 4 | High | Blocking `subprocess.run` in async ASR adapter | 5 |

---

### Task 1: Remove Debug Desktop File Write

**Files:**
- Modify: `src/api/app.py:462-466`

**Step 1: Delete the debug file write block**

In `src/api/app.py`, remove these lines (inside the `/dialogue/voice` endpoint):

```python
        # 保存一份到桌面用於調試
        debug_file = "C:/Users/User/Desktop/debug_recording.webm"
        with open(debug_file, "wb") as f:
            f.write(content)
        debug(f"已保存調試檔案到: {debug_file}")
```

**Step 2: Verify the server still starts**

Run: `cd src && python -c "from api.app import app; print('OK')"`
Expected: `OK` (no import errors)

**Step 3: Commit**

```bash
git add src/api/app.py
git commit -m "fix: remove debug desktop file write from /dialogue/voice"
```

---

### Task 2: Fix API Key Exposure — Remove Auth from Checkout Endpoint

Since all `/api/*` requests are proxied through Next.js rewrites (`next.config.ts:6-8`), the backend is not directly exposed to the public. The checkout endpoint doesn't need API Key auth — it should work the same way as `/api/voice-chat` (which uses optional auth).

**Files:**
- Modify: `src/api/app.py:682-683`
- Modify: `src/frontend_next/components/CheckoutFlow.tsx:55-66`

**Step 1: Remove `api_key` dependency from checkout endpoint**

In `src/api/app.py`, change the `checkout` function signature from:

```python
@app.post("/api/checkout")
async def checkout(request: CheckoutRequest, api_key: str = Depends(get_api_key)):
```

to:

```python
@app.post("/api/checkout")
async def checkout(request: CheckoutRequest):
```

**Step 2: Remove API Key header from CheckoutFlow.tsx**

In `src/frontend_next/components/CheckoutFlow.tsx`, change the fetch call from:

```typescript
      const response = await fetch('/api/checkout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': 'yuan-secret-key',
        },
        body: JSON.stringify({
```

to:

```typescript
      const response = await fetch('/api/checkout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
```

**Step 3: Verify the server still starts**

Run: `cd src && python -c "from api.app import app; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/api/app.py src/frontend_next/components/CheckoutFlow.tsx
git commit -m "fix: remove hardcoded API key from checkout — use proxy-only access"
```

---

### Task 3: Add Empty Cart Guard to Checkout

**Files:**
- Modify: `src/api/app.py` (inside `checkout` function, after reading cart)

**Step 1: Add empty cart check**

In `src/api/app.py`, after line 706 (`cart = session.get("cart", [])`), add:

```python
        if not cart:
            raise HTTPException(status_code=400, detail="購物車是空的，無法結帳")
```

This goes right after `cart = session.get("cart", [])` and before `llm_history = session.get(...)`.

**Step 2: Verify the server still starts**

Run: `cd src && python -c "from api.app import app; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/api/app.py
git commit -m "fix: reject checkout with empty cart (400 error)"
```

---

### Task 4: Fix Order Number Race Condition + Remove Dead Code

**Files:**
- Modify: `src/repository/order_repository.py:96-119`

**Step 1: Rewrite `get_next_order_number` with transaction safety**

Replace the entire `get_next_order_number` method with:

```python
    def get_next_order_number(self) -> str:
        """
        獲取今天的下一個取餐號碼
        規則：每日 00:00 重置回 01，最少兩位補零（01, 02, ... 99, 100）
        使用 BEGIN IMMEDIATE 避免競態條件
        """
        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM orders WHERE created_at LIKE ?
            """, (f"{today}%",)).fetchone()

            next_num = (row["cnt"] or 0) + 1
            conn.commit()
            return f"{next_num:02d}"
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

This removes the unused `MAX(CAST(SUBSTR(...)))` dead code and adds `BEGIN IMMEDIATE` to prevent two concurrent requests from getting the same count.

**Note:** For full safety, the order number generation should be inside the same transaction as `save_order`. But since this is a single-store kiosk app (not high-concurrency), `BEGIN IMMEDIATE` is sufficient to serialize access.

**Step 2: Verify the server still starts**

Run: `cd src && python -c "from repository.order_repository import OrderRepository; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/repository/order_repository.py
git commit -m "fix: prevent order number race condition with IMMEDIATE transaction"
```

---

### Task 5: Fix Blocking subprocess.run in Async ASR Adapter

**Files:**
- Modify: `src/api/voice_router.py:60-87` (ASRAdapter class)

**Step 1: Replace `subprocess.run` with `asyncio.create_subprocess_exec`**

Replace the `ASRAdapter` class with:

```python
    class ASRAdapter:
        def __init__(self, asr_service):
            self._asr = asr_service

        async def transcribe(self, audio_bytes: bytes) -> str:
            import asyncio
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            wav_path = tmp_path.replace(".webm", ".wav")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", tmp_path,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(f"ffmpeg failed: {stderr.decode()[:200]}")

                os.unlink(tmp_path)
                result = self._asr.transcribe(wav_path)
                return result.get("text", "")
            finally:
                for p in [tmp_path, wav_path]:
                    if os.path.exists(p):
                        os.unlink(p)
```

**Step 2: Verify the server still starts**

Run: `cd src && python -c "from api.app import app; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/api/voice_router.py
git commit -m "fix: use async subprocess for ffmpeg in ASR adapter"
```

---

## Not Addressed (Low Priority — Future)

These were flagged in the review but are not worth fixing right now:

- **#7** (StreamingOrchestrator session_id mutation) — No practical impact since each request creates a new instance
- **#9** (VoiceController missing API Key) — Moot after Task 2 aligns everything to optional auth
- **#10** (Cart item `price` field assumption) — Needs broader cart data model discussion
- **#11** (Duplicate `debug()` closures) — Cosmetic, low risk
- **#12** (EdgeTTSModel re-instantiation) — Negligible cost
- **#13** (Circular import via lazy import) — Architectural tech debt, not a bug
