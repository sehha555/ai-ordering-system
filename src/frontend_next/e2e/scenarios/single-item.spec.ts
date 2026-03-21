/**
 * 單品點餐 E2E 測試
 * Layer 3 Full Stack — 需要 backend + LM Studio
 *
 * TODO: 拿到菜單後更新 ITEM_NAME / ITEM_PRICE
 */
import { test, expect } from '@playwright/test'
import { captureVoiceSSE, captureTextSSE } from '../helpers/sseCapture'
import { loadAudioBase64 } from '../helpers/audioLoader'
import { attachSSEReport, assertCart, assertToolCalled, assertTTS, assertNoError } from '../helpers/report'

// TODO: 拿到菜單後替換
const ITEM_NAME = '{{品項1}}'      // e.g. '鮪魚飯糰'
const ITEM_PRICE = 0               // e.g. 50

test.describe('單品點餐 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend + LM Studio')

  const SESSION_ID = `e2e-single-${Date.now()}`

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
  })

  test('語音點單品 → 購物車出現品項 + TTS 回覆', async ({ page }, testInfo) => {
    const audio = await loadAudioBase64('single_item')
    const result = await captureVoiceSSE(page, audio, SESSION_ID)

    const assertions = [
      ...assertNoError(result),
      ...assertToolCalled(result, 'add_to_cart'),
      ...assertCart(result, { nameIncludes: ITEM_NAME, quantity: 1, minTotal: ITEM_PRICE }),
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('文字點單品 → 購物車出現品項', async ({ page }, testInfo) => {
    const result = await captureTextSSE(page, `我要一個${ITEM_NAME}`, SESSION_ID + '-text')

    const assertions = [
      ...assertNoError(result),
      ...assertToolCalled(result, 'add_to_cart'),
      ...assertCart(result, { nameIncludes: ITEM_NAME, quantity: 1 }),
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('ASR 轉錄結果不為空', async ({ page }, testInfo) => {
    const audio = await loadAudioBase64('single_item')
    const result = await captureVoiceSSE(page, audio, SESSION_ID + '-asr')

    const assertions = [
      ...assertNoError(result),
      {
        name: 'ASR 轉錄不為空',
        passed: !!result.transcription && result.transcription.length > 0,
        detail: `轉錄結果：${result.transcription}`,
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })
})
