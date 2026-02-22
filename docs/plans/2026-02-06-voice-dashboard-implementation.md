# Voice Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the existing backend into a streaming-capable API (SSE) and build a modern Next.js Voice Dashboard frontend.

**Architecture:**
- **Backend:** FastAPI with Server-Sent Events (SSE). New abstract TTS layer for streaming audio chunks.
- **Frontend:** Next.js 14+ (App Router), Tailwind CSS, Zustand, Framer Motion. Uses Web Audio API for visualizer.
- **Protocol:** POST audio blob -> Receive SSE stream (transcription, cart updates, audio chunks).

**Tech Stack:** Python 3.10+, FastAPI, SSE-Starlette (or native StreamingResponse), Next.js, React, Tailwind, Framer Motion.

---

## Phase 1: Backend Streaming Adaptation

### Task 1.1: Create TTS Abstraction Layer

**Goal:** Define a protocol for TTS services to yield audio bytes, allowing easy switching between providers (EdgeTTS, OpenAI).

**Files:**
- Create: `src/services/tts_interface.py`
- Create: `src/services/tts_implementations.py`
- Test: `tests/services/test_tts_streaming.py`

**Step 1: Write the failing test for TTS Interface**

```python
# tests/services/test_tts_streaming.py
import pytest
import asyncio
from typing import AsyncIterator
from src.services.tts_interface import TTSModel

class MockTTS(TTSModel):
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

@pytest.mark.asyncio
async def test_tts_interface_contract():
    tts = MockTTS()
    chunks = []
    async for chunk in tts.run_stream("hello"):
        chunks.append(chunk)
    assert chunks == [b"chunk1", b"chunk2"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_tts_streaming.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Implement TTS Interface**

```python
# src/services/tts_interface.py
from abc import ABC, abstractmethod
from typing import AsyncIterator

class TTSModel(ABC):
    @abstractmethod
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (PCM or MP3 frames)"""
        pass
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/services/test_tts_streaming.py -v`
Expected: PASS

**Step 5: Implement EdgeTTS Adapter (Skeleton)**

Add to `src/services/tts_implementations.py`:
```python
from typing import AsyncIterator
import edge_tts
from src.services.tts_interface import TTSModel

class EdgeTTSModel(TTSModel):
    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        self.voice = voice

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        communicate = edge_tts.Communicate(text, self.voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
```

**Step 6: Commit**

```bash
git add src/services/tts_interface.py src/services/tts_implementations.py tests/services/test_tts_streaming.py
git commit -m "feat(backend): add TTS streaming abstraction layer"
```

---

### Task 1.2: Implement Streaming Logic Service

**Goal:** Create a service that orchestrates ASR -> DM -> TTS and yields SSE events.

**Files:**
- Create: `src/services/streaming_orchestrator.py`
- Test: `tests/services/test_streaming_orchestrator.py`

**Step 1: Write the failing test**

```python
# tests/services/test_streaming_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.streaming_orchestrator import StreamingOrchestrator

@pytest.mark.asyncio
async def test_orchestrator_flow():
    # Mock dependencies
    mock_asr = AsyncMock()
    mock_asr.transcribe.return_value = "我要一個飯糰"
    
    mock_dm = MagicMock()
    mock_dm.process_input.return_value = ("好的，一個飯糰", {"cart": []})
    
    mock_tts = AsyncMock()
    # Mock async generator for TTS
    async def async_gen(text):
        yield b"audio_data"
    mock_tts.run_stream = async_gen

    orchestrator = StreamingOrchestrator(mock_asr, mock_dm, mock_tts)
    
    events = []
    async for event in orchestrator.process_audio_stream(b"fake_audio_blob"):
        events.append(event)
    
    # Verify sequence of events
    event_types = [e["event"] for e in events]
    assert "transcription" in event_types
    assert "thinking" in event_types
    assert "cart_update" in event_types
    assert "audio_chunk" in event_types
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_streaming_orchestrator.py -v`
Expected: FAIL

**Step 3: Implement StreamingOrchestrator**

```python
# src/services/streaming_orchestrator.py
import json
import base64
from typing import AsyncIterator, Dict, Any

class StreamingOrchestrator:
    def __init__(self, asr_service, dialogue_manager, tts_service):
        self.asr = asr_service
        self.dm = dialogue_manager
        self.tts = tts_service

    async def process_audio_stream(self, audio_bytes: bytes) -> AsyncIterator[Dict[str, Any]]:
        # 1. Thinking
        yield {"event": "thinking", "data": {}}

        # 2. ASR
        text = await self.asr.transcribe(audio_bytes) # Assume transcribe accepts bytes directly or needs adaptation
        yield {"event": "transcription", "data": {"text": text}}

        # 3. DM
        # Note: In real app, we need session_id. For now, assume stateless or passed in.
        # This is a simplification. The DM is synchronous, so we run it directly.
        response_text, context_snapshot = self.dm.process_input(text) 
        
        # 4. Cart Update
        cart = context_snapshot.get("cart", [])
        total = context_snapshot.get("order_payload", {}).get("total_price", 0)
        yield {"event": "cart_update", "data": {"items": cart, "total": total}}

        # 5. TTS Streaming
        async for chunk in self.tts.run_stream(response_text):
            b64_audio = base64.b64encode(chunk).decode('utf-8')
            yield {"event": "audio_chunk", "data": b64_audio}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/services/test_streaming_orchestrator.py -v`
Expected: PASS (Note: You might need to adjust ASR service call if it expects a file path, possibly using `tempfile`)

**Step 5: Commit**

```bash
git add src/services/streaming_orchestrator.py tests/services/test_streaming_orchestrator.py
git commit -m "feat(backend): add streaming orchestrator for SSE events"
```

---

### Task 1.3: Add SSE Endpoint to FastAPI

**Goal:** Expose the streaming logic via a POST endpoint.

**Files:**
- Modify: `src/api/app.py`
- Create: `src/api/voice_router.py`

**Step 1: Create Voice Router**

```python
# src/api/voice_router.py
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
import json
import asyncio

# Dependencies would be injected in real app
from src.services.streaming_orchestrator import StreamingOrchestrator
# Import your actual service instances or factories here

router = APIRouter()

async def event_generator(orchestrator, audio_bytes):
    async for event in orchestrator.process_audio_stream(audio_bytes):
        # Format as SSE
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

@router.post("/voice-chat")
async def voice_chat(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    
    # TODO: Instantiate services properly (DI recommended)
    # For now, we assume global instances or creation on fly for prototype
    # orchestrator = get_orchestrator() 
    
    # Return StreamingResponse
    # return StreamingResponse(event_generator(orchestrator, audio_bytes), media_type="text/event-stream")
    pass # Placeholder for plan
```

**Step 2: Update App**

Modify `src/api/app.py` to include the new router.

**Step 3: Commit**

```bash
git add src/api/voice_router.py src/api/app.py
git commit -m "feat(backend): add /api/voice-chat SSE endpoint"
```

---

## Phase 2: Frontend Implementation (Next.js)

### Task 2.1: Initialize Next.js Project

**Goal:** Set up the Next.js framework with Tailwind CSS in a subdirectory (or root if we move files). For this plan, we\'ll create it in `src/frontend_next`.

**Files:**
- Run: `npx create-next-app@latest src/frontend_next --typescript --tailwind --eslint`

**Step 1: Run create-next-app**

Run: `npx create-next-app@latest src/frontend_next --typescript --tailwind --eslint --no-src-dir --import-alias "@/*" --app --use-npm`

**Step 2: Configure Proxy**

Modify `src/frontend_next/next.config.mjs` to proxy `/api` requests to `http://localhost:8000`.

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*',
      },
    ]
  },
};
export default nextConfig;
```

**Step 3: Commit**

```bash
git add src/frontend_next
git commit -m "chore(frontend): init next.js project"
```

---

### Task 2.2: Setup Zustand Store & Types

**Goal:** Define the state for the cart and recording status.

**Files:**
- Create: `src/frontend_next/store/useStore.ts`
- Create: `src/frontend_next/types/index.ts`

**Step 1: Define Types**

```typescript
// src/frontend_next/types/index.ts
export interface CartItem {
    name: string;
    details: string; // e.g. "大杯, 半糖"
    price: number;
    quantity: number;
}

export interface AppState {
    status: 'idle' | 'listening' | 'processing' | 'speaking';
    cart: CartItem[];
    total: number;
    transcript: string;
    setStatus: (s: AppState['status']) => void;
    setCart: (items: CartItem[], total: number) => void;
    setTranscript: (t: string) => void;
}
```

**Step 2: Create Store**

```typescript
// src/frontend_next/store/useStore.ts
import { create } from 'zustand';
import { AppState } from '../types';

export const useStore = create<AppState>((set) => ({
    status: 'idle',
    cart: [],
    total: 0,
    transcript: '',
    setStatus: (status) => set({ status }),
    setCart: (cart, total) => set({ cart, total }),
    setTranscript: (transcript) => set({ transcript }),
}));
```

**Step 3: Commit**

```bash
git add src/frontend_next/store src/frontend_next/types
git commit -m "feat(frontend): add zustand store and types"
```

---

### Task 2.3: Implement Audio Visualizer

**Goal:** Create the `AudioVisualizer` component that reacts to state.

**Files:**
- Create: `src/frontend_next/components/AudioVisualizer.tsx`

**Step 1: Create Component Skeleton**

Create a component that uses a `canvas` ref and runs a requestAnimationFrame loop. It should accept `status` as a prop to change colors.

**Step 2: Add Visual Logic**

Implement simple circular wave animation.
- Idle: Slow breathing radius.
- Listening: Radius reacts to `volume` prop (passed from parent).

**Step 3: Commit**

```bash
git add src/frontend_next/components/AudioVisualizer.tsx
git commit -m "feat(frontend): add audio visualizer component"
```

---

### Task 2.4: Implement Voice Controller (Recording & SSE)

**Goal:** The brain of the frontend. Handles mic input, VAD (simplified), POST request, and SSE parsing.

**Files:**
- Create: `src/frontend_next/components/VoiceController.tsx`

**Step 1: Implement Recording**

Use `MediaRecorder`. On stop, create Blob.

**Step 2: Implement SSE Fetch**

```typescript
// inside sendAudio function
const response = await fetch('/api/voice-chat', {
    method: 'POST',
    body: formData,
});

const reader = response.body?.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value);
    // Parse "event: ... \ndata: ..." strings
    // Update store based on event
    // Queue audio chunks for playback
}
```

**Step 3: Implement Audio Playback Queue**

Simple queue system that plays the next blob when the previous one `onended`.

**Step 4: Commit**

```bash
git add src/frontend_next/components/VoiceController.tsx
git commit -m "feat(frontend): add voice controller with SSE support"
```

---

### Task 2.5: Build Main Page Layout

**Goal:** Assemble the Dashboard.

**Files:**
- Modify: `src/frontend_next/app/page.tsx`
- Create: `src/frontend_next/components/LiveReceipt.tsx`

**Step 1: Create LiveReceipt**

A component that maps `useStore(state => state.cart)` to a list of cards. Use framer-motion `AnimatePresence` for entry animations.

**Step 2: Assemble Page**

Layout with:
- Center: `AudioVisualizer` wrapped in `VoiceController`.
- Right Sidebar: `LiveReceipt`.
- Global bg color: `#F5F7F8`.

**Step 3: Commit**

```bash
git add src/frontend_next/app/page.tsx src/frontend_next/components/LiveReceipt.tsx
git commit -m "feat(frontend): assemble main voice dashboard layout"
```
