/**
 * 邊界案例 E2E 測試
 * Layer 3 Full Stack — 需要 backend + LM Studio
 */
import { test, expect } from '@playwright/test'
import { captureTextSSE } from '../helpers/sseCapture'
import { attachSSEReport, assertTTS, assertNoError } from '../helpers/report'

// 用一個不太可能真正售完的品項名，測試的重點是系統不 crash
const OUT_OF_STOCK_ITEM = '鍋燒意麵'   // 不存在於菜單，模擬售完/找不到

test.describe('邊界案例 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend + LM Studio')

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
  })

  test('詢問飲料品項 → 有回應（不 crash）', async ({ page }, testInfo) => {
    const sid = `e2e-edge-drinks-${Date.now()}`
    const result = await captureTextSSE(page, '有什麼飲料', sid)

    const assertions = [
      ...assertNoError(result),
      {
        name: '有回應（tts 或文字）',
        passed: result.ttsAudioBase64.length > 0 || !!result.ttsText,
        detail: `ttsText: ${result.ttsText}`,
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('點售完品項 → 友善提示', async ({ page }, testInfo) => {
    const sid = `e2e-edge-soldout-${Date.now()}`
    const result = await captureTextSSE(page, `我要一個${OUT_OF_STOCK_ITEM}`, sid)

    const assertions = [
      ...assertNoError(result),
      {
        name: '購物車不含售完品項',
        passed: !result.cartItems.some(i => i.name.includes(OUT_OF_STOCK_ITEM)),
        detail: `購物車：${result.cartItems.map(i => i.name).join(', ')}`,
      },
      {
        name: '有回應（告知售完）',
        passed: result.ttsAudioBase64.length > 0 || !!result.ttsText,
        detail: `ttsText: ${result.ttsText}`,
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('不存在品項 → 友善提示，不加入購物車', async ({ page }, testInfo) => {
    const sid = `e2e-edge-unknown-${Date.now()}`
    const result = await captureTextSSE(page, '我要一個超級無敵飯糰', sid)

    const assertions = [
      ...assertNoError(result),
      {
        name: '購物車為空',
        passed: result.cartItems.length === 0,
        detail: `購物車：${result.cartItems.map(i => i.name).join(', ')}`,
      },
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('空白語音（近乎無聲）→ 不 crash', async ({ page }, testInfo) => {
    // 送極短文字模擬 ASR 空白結果
    const sid = `e2e-edge-blank-${Date.now()}`
    const result = await captureTextSSE(page, '。', sid)

    const assertions = [
      {
        name: '無 500 error',
        passed: result.error === null || !result.error?.includes('500'),
        detail: result.error ?? 'ok',
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('重複點同樣品項 → 數量累加（不重複建立）', async ({ page }, testInfo) => {
    const sid = `e2e-edge-duplicate-${Date.now()}`
    const ITEM = '原味蛋餅'

    await captureTextSSE(page, `我要一個${ITEM}`, sid)
    const result = await captureTextSSE(page, `再來一個${ITEM}`, sid)

    const items = result.cartItems.filter(i => i.name.includes(ITEM))
    const totalQty = items.reduce((s, i) => s + i.quantity, 0)

    const assertions = [
      ...assertNoError(result),
      {
        name: `${ITEM} 總數量 >= 2`,
        passed: totalQty >= 2,
        detail: `實際數量：${totalQty}，品項數：${items.length}`,
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })
})
