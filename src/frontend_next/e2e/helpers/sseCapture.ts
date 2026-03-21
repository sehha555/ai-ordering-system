/**
 * SSE 捕捉工具
 * 透過 page.evaluate() 在瀏覽器上下文執行 fetch，串流讀取所有 SSE 事件。
 */
import type { Page } from '@playwright/test'

export interface SSEEvent {
  event: string
  data: Record<string, unknown>
}

export interface CartItem {
  name: string
  details: string
  price: number
  quantity: number
}

export interface CaptureResult {
  events: SSEEvent[]
  transcription: string | null
  cartItems: CartItem[]
  total: number
  toolsInvoked: string[]
  ttsAudioBase64: string[]   // 每段 audio_chunk
  ttsText: string | null
  error: string | null
}

export async function captureVoiceSSE(
  page: Page,
  audioBase64: string,
  sessionId: string,
  timeoutMs = 45000
): Promise<CaptureResult> {
  const events: SSEEvent[] = await page.evaluate(
    async ({ audioBase64, sessionId, timeoutMs }) => {
      const bytes = Uint8Array.from(atob(audioBase64), c => c.charCodeAt(0))
      const blob = new Blob([bytes], { type: 'audio/mpeg' })

      const formData = new FormData()
      formData.append('file', blob, 'test.mp3')
      formData.append('session_id', sessionId)

      const controller = new AbortController()
      const tid = setTimeout(() => controller.abort(), timeoutMs)

      const response = await fetch('/api/voice-chat', {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      })

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      const events: Array<{ event: string; data: Record<string, unknown> }> = []
      let buffer = ''
      let currentEvent = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          const parts = buffer.split('\n\n')
          buffer = parts.pop() ?? ''

          for (const part of parts) {
            for (const line of part.split('\n')) {
              if (line.startsWith('event: ')) {
                currentEvent = line.slice(7).trim()
              } else if (line.startsWith('data: ')) {
                try {
                  events.push({ event: currentEvent, data: JSON.parse(line.slice(6)) })
                } catch {
                  events.push({ event: currentEvent, data: { raw: line.slice(6) } })
                }
              }
            }
          }

          if (events.some(e => e.event === 'done' || e.event === 'error')) break
        }
      } finally {
        clearTimeout(tid)
        reader.cancel().catch(() => {})
      }

      return events
    },
    { audioBase64, sessionId, timeoutMs }
  )

  return parseEvents(events)
}

export async function captureTextSSE(
  page: Page,
  text: string,
  sessionId: string,
  timeoutMs = 30000
): Promise<CaptureResult> {
  const events: SSEEvent[] = await page.evaluate(
    async ({ text, sessionId, timeoutMs }) => {
      const controller = new AbortController()
      const tid = setTimeout(() => controller.abort(), timeoutMs)

      const response = await fetch('/api/text-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: sessionId }),
        signal: controller.signal,
      })

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      const events: Array<{ event: string; data: Record<string, unknown> }> = []
      let buffer = ''
      let currentEvent = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          const parts = buffer.split('\n\n')
          buffer = parts.pop() ?? ''

          for (const part of parts) {
            for (const line of part.split('\n')) {
              if (line.startsWith('event: ')) {
                currentEvent = line.slice(7).trim()
              } else if (line.startsWith('data: ')) {
                try {
                  events.push({ event: currentEvent, data: JSON.parse(line.slice(6)) })
                } catch {
                  events.push({ event: currentEvent, data: { raw: line.slice(6) } })
                }
              }
            }
          }

          if (events.some(e => e.event === 'done' || e.event === 'error')) break
        }
      } finally {
        clearTimeout(tid)
        reader.cancel().catch(() => {})
      }

      return events
    },
    { text, sessionId, timeoutMs }
  )

  return parseEvents(events)
}

function parseEvents(events: SSEEvent[]): CaptureResult {
  const cartUpdate = events.findLast(e => e.event === 'cart_update')
  const ttsTextEvent = events.find(e => e.event === 'tts_text')
  const errorEvent = events.find(e => e.event === 'error')
  const transcriptionEvent = events.find(e => e.event === 'transcription')

  // 從 status 事件推斷呼叫了哪些工具
  const TOOL_STATUS_MAP: Record<string, string> = {
    '正在加入購物車': 'add_to_cart',
    '正在確認訂單': 'finalize_order',
    '正在準備結帳預覽': 'preview_checkout',
    '正在查詢菜單': 'query_menu',
    '正在查詢價格': 'get_price',
    '正在移除品項': 'remove_from_cart',
    '正在整理購物車': 'get_cart_summary',
  }
  const toolsInvoked: string[] = []
  for (const e of events) {
    if (e.event === 'status') {
      const msg = (e.data.message as string) ?? ''
      for (const [kw, tool] of Object.entries(TOOL_STATUS_MAP)) {
        if (msg.includes(kw) && !toolsInvoked.includes(tool)) {
          toolsInvoked.push(tool)
        }
      }
    }
  }

  const ttsChunks = events
    .filter(e => e.event === 'audio_chunk')
    .map(e => e.data.data as string ?? '')

  return {
    events,
    transcription: transcriptionEvent ? (transcriptionEvent.data.text as string) : null,
    cartItems: (cartUpdate?.data.items as CartItem[]) ?? [],
    total: (cartUpdate?.data.total as number) ?? 0,
    toolsInvoked,
    ttsAudioBase64: ttsChunks,
    ttsText: ttsTextEvent ? (ttsTextEvent.data.text as string) : null,
    error: errorEvent ? (errorEvent.data.message as string) : null,
  }
}
