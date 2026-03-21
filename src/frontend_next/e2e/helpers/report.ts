/**
 * E2E 測試報告工具
 * 將每個 scenario 的結果寫入 JSON，並附加到 Playwright 測試附件。
 */
import { writeFile, mkdir } from 'fs/promises'
import path from 'path'
import type { TestInfo } from '@playwright/test'
import type { CaptureResult } from './sseCapture'

const REPORT_DIR = path.join(__dirname, '..', '..', 'test-results', 'e2e-report')

export interface ScenarioResult {
  scenario: string
  timestamp: string
  passed: boolean
  transcription: string | null
  toolsInvoked: string[]
  cartItems: { name: string; quantity: number; price: number }[]
  total: number
  ttsReceived: boolean
  ttsText: string | null
  error: string | null
  assertions: { name: string; passed: boolean; detail?: string }[]
}

export async function attachSSEReport(
  testInfo: TestInfo,
  result: CaptureResult,
  assertions: ScenarioResult['assertions']
): Promise<void> {
  const report: ScenarioResult = {
    scenario: testInfo.title,
    timestamp: new Date().toISOString(),
    passed: assertions.every(a => a.passed),
    transcription: result.transcription,
    toolsInvoked: result.toolsInvoked,
    cartItems: result.cartItems.map(i => ({
      name: i.name,
      quantity: i.quantity,
      price: i.price,
    })),
    total: result.total,
    ttsReceived: result.ttsAudioBase64.length > 0,
    ttsText: result.ttsText,
    error: result.error,
    assertions,
  }

  // Playwright 附件（HTML report 可檢視）
  await testInfo.attach('sse-report', {
    contentType: 'application/json',
    body: Buffer.from(JSON.stringify(report, null, 2)),
  })

  await testInfo.attach('sse-events', {
    contentType: 'application/json',
    body: Buffer.from(JSON.stringify(result.events, null, 2)),
  })

  // 若有 TTS 音訊，儲存第一段供人工聆聽
  if (result.ttsAudioBase64.length > 0) {
    const firstChunk = Buffer.from(result.ttsAudioBase64[0], 'base64')
    await testInfo.attach('tts-audio-chunk', {
      contentType: 'audio/mpeg',
      body: firstChunk,
    })
  }

  // 同時寫入 JSON 檔（CI artifact 用）
  await mkdir(REPORT_DIR, { recursive: true })
  const safeName = testInfo.title.replace(/[^\w\u4e00-\u9fff]/g, '_')
  await writeFile(
    path.join(REPORT_DIR, `${safeName}.json`),
    JSON.stringify(report, null, 2),
    'utf-8'
  )
}

export function assertCart(
  result: CaptureResult,
  expected: { nameIncludes: string; quantity?: number; minTotal?: number }
): ScenarioResult['assertions'] {
  const assertions: ScenarioResult['assertions'] = []

  const found = result.cartItems.find(i => i.name.includes(expected.nameIncludes))
  assertions.push({
    name: `購物車包含「${expected.nameIncludes}」`,
    passed: !!found,
    detail: found ? `找到：${found.name}` : `未找到，實際：${result.cartItems.map(i => i.name).join(', ')}`,
  })

  if (expected.quantity !== undefined && found) {
    assertions.push({
      name: `數量 = ${expected.quantity}`,
      passed: found.quantity === expected.quantity,
      detail: `實際數量：${found?.quantity}`,
    })
  }

  if (expected.minTotal !== undefined) {
    assertions.push({
      name: `總金額 >= ${expected.minTotal}`,
      passed: result.total >= expected.minTotal,
      detail: `實際總金額：${result.total}`,
    })
  }

  return assertions
}

export function assertToolCalled(
  result: CaptureResult,
  toolName: string
): ScenarioResult['assertions'] {
  return [{
    name: `工具 ${toolName} 被呼叫`,
    passed: result.toolsInvoked.includes(toolName),
    detail: `實際呼叫：${result.toolsInvoked.join(', ') || '（無）'}`,
  }]
}

export function assertTTS(result: CaptureResult): ScenarioResult['assertions'] {
  return [{
    name: 'TTS 音訊已回傳',
    passed: result.ttsAudioBase64.length > 0,
    detail: `收到 ${result.ttsAudioBase64.length} 段 audio_chunk`,
  }]
}

export function assertNoError(result: CaptureResult): ScenarioResult['assertions'] {
  return [{
    name: '無錯誤事件',
    passed: result.error === null,
    detail: result.error ?? 'ok',
  }]
}
