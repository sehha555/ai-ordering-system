/**
 * 多品點餐 E2E 測試
 * Layer 3 Full Stack — 需要 backend + LM Studio
 *
 * TODO: 拿到菜單後更新 ITEM_* / DRINK_*
 */
import { test, expect } from '@playwright/test'
import { captureVoiceSSE, captureTextSSE } from '../helpers/sseCapture'
import { loadAudioBase64 } from '../helpers/audioLoader'
import { attachSSEReport, assertCart, assertToolCalled, assertTTS, assertNoError } from '../helpers/report'

// TODO: 拿到菜單後替換
const ITEM_1 = '{{品項1}}'    // e.g. '鮪魚飯糰'
const DRINK_1 = '{{飲料1}}'   // e.g. '大冰奶茶'
const ITEM_1_PRICE = 0        // e.g. 50
const DRINK_1_PRICE = 0       // e.g. 35

test.describe('多品點餐 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend + LM Studio')

  const SESSION_ID = `e2e-multi-${Date.now()}`

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
  })

  test('語音點飯糰+飲料 → 購物車含兩品項', async ({ page }, testInfo) => {
    const audio = await loadAudioBase64('multi_item')
    const result = await captureVoiceSSE(page, audio, SESSION_ID)

    const assertions = [
      ...assertNoError(result),
      ...assertToolCalled(result, 'add_to_cart'),
      ...assertCart(result, { nameIncludes: ITEM_1 }),
      ...assertCart(result, { nameIncludes: DRINK_1 }),
      ...assertCart(result, { nameIncludes: ITEM_1, minTotal: ITEM_1_PRICE + DRINK_1_PRICE }),
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('分兩次點餐 → 購物車累加', async ({ page }, testInfo) => {
    const sessionId = SESSION_ID + '-sequential'

    // 第一次：點飯糰
    const result1 = await captureTextSSE(page, `我要一個${ITEM_1}`, sessionId)
    // 第二次：加飲料
    const result2 = await captureTextSSE(page, `再來一杯${DRINK_1}`, sessionId)

    const assertions = [
      ...assertNoError(result1),
      ...assertNoError(result2),
      ...assertCart(result2, { nameIncludes: ITEM_1 }),
      ...assertCart(result2, { nameIncludes: DRINK_1 }),
      ...assertTTS(result2),
    ]

    await attachSSEReport(testInfo, result2, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('文字點多品 → 購物車含兩品項', async ({ page }, testInfo) => {
    const result = await captureTextSSE(
      page,
      `我要一個${ITEM_1}跟一杯${DRINK_1}`,
      SESSION_ID + '-text'
    )

    const assertions = [
      ...assertNoError(result),
      ...assertCart(result, { nameIncludes: ITEM_1 }),
      ...assertCart(result, { nameIncludes: DRINK_1 }),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })
})
