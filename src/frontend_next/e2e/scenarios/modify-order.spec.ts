/**
 * 修改訂單 E2E 測試（加單、移除、清空）
 * Layer 3 Full Stack — 需要 backend + LM Studio
 */
import { test, expect } from '@playwright/test'
import { captureTextSSE } from '../helpers/sseCapture'
import { attachSSEReport, assertCart, assertTTS, assertNoError, ScenarioResult } from '../helpers/report'

const ITEM_1 = '原味蛋餅'
const ITEM_2 = '起司蛋餅'

test.describe('修改訂單 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend + LM Studio')

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
  })

  test('加單 → 數量 +1', async ({ page }, testInfo) => {
    const sid = `e2e-modify-add-${Date.now()}`

    // 先點一個
    await captureTextSSE(page, `我要一個${ITEM_1}`, sid)
    // 再加一個同品項
    const result = await captureTextSSE(page, `再來一個${ITEM_1}`, sid)

    // 系統每次 ADD 建獨立條目，檢查總數量而非單一 quantity 欄位
    const matchingItems = result.cartItems.filter(i => i.name.includes(ITEM_1))
    const totalQty = matchingItems.reduce((s, i) => s + i.quantity, 0)

    const assertions = [
      ...assertNoError(result),
      {
        name: `${ITEM_1} 總數量 >= 2`,
        passed: totalQty >= 2,
        detail: `實際數量：${totalQty}，品項數：${matchingItems.length}`,
      },
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('移除品項 → 購物車不含該品項', async ({ page }, testInfo) => {
    const sid = `e2e-modify-remove-${Date.now()}`

    // 先點兩種
    await captureTextSSE(page, `我要一個${ITEM_1}`, sid)
    await captureTextSSE(page, `還有一個${ITEM_2}`, sid)
    // 移除第一個
    const result = await captureTextSSE(page, `不要${ITEM_1}了`, sid)

    const itemStillInCart = result.cartItems.find(i => i.name.includes(ITEM_1))

    const assertions = [
      ...assertNoError(result),
      {
        name: `購物車不含「${ITEM_1}」`,
        passed: !itemStillInCart,
        detail: itemStillInCart
          ? `${ITEM_1} 仍在購物車`
          : `已移除，購物車：${result.cartItems.map(i => i.name).join(', ')}`,
      },
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('清空購物車 → 購物車為空', async ({ page }, testInfo) => {
    const sid = `e2e-modify-clear-${Date.now()}`

    await captureTextSSE(page, `我要一個${ITEM_1}`, sid)
    const result = await captureTextSSE(page, '全部清掉', sid)

    const assertions = [
      ...assertNoError(result),
      {
        name: '購物車為空',
        passed: result.cartItems.length === 0 && result.total === 0,
        detail: `購物車：${JSON.stringify(result.cartItems)}，總計：${result.total}`,
      },
      ...assertTTS(result),
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('修改空購物車 → 友善提示（不 crash）', async ({ page }, testInfo) => {
    const sid = `e2e-modify-empty-${Date.now()}`

    // 不點任何東西直接移除
    const result = await captureTextSSE(page, '不要剛剛那個', sid)

    const assertions = [
      ...assertNoError(result),
      {
        name: '有回應文字（不 crash）',
        passed: !!result.ttsText || result.ttsAudioBase64.length > 0,
        detail: `ttsText：${result.ttsText}`,
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })
})
