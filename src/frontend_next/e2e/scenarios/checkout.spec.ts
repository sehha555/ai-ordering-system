/**
 * 結帳流程 E2E 測試
 * Layer 3 Full Stack — 需要 backend + LM Studio
 */
import { test, expect } from '@playwright/test'
import { captureTextSSE, CaptureResult } from '../helpers/sseCapture'
import { attachSSEReport, assertTTS, assertNoError } from '../helpers/report'

const ITEM_1 = '原味蛋餅'

test.describe('結帳流程 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend + LM Studio')

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
  })

  test('完整結帳流程：點餐 → 結帳 → 內用 → 現金', async ({ page }, testInfo) => {
    const sid = `e2e-checkout-full-${Date.now()}`
    const results: CaptureResult[] = []

    // 1. 點餐
    results.push(await captureTextSSE(page, `我要一個${ITEM_1}`, sid))
    // 2. 觸發結帳
    results.push(await captureTextSSE(page, '幫我結帳', sid))
    // 3. 選內用
    results.push(await captureTextSSE(page, '內用', sid))
    // 4. 選現金
    const finalResult = await captureTextSSE(page, '付現金', sid)
    results.push(finalResult)

    const orderComplete = finalResult.events.find(e => e.event === 'order_complete')

    const assertions = [
      ...assertNoError(finalResult),
      ...assertTTS(finalResult),
      {
        name: '收到 order_complete 事件',
        passed: !!orderComplete,
        detail: orderComplete ? JSON.stringify(orderComplete.data) : '未收到',
      },
      {
        name: '訂單號碼存在',
        passed: !!orderComplete?.data?.order_number,
        detail: `訂單號：${orderComplete?.data?.order_number}`,
      },
    ]

    await attachSSEReport(testInfo, finalResult, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('空購物車結帳 → 提示先點餐', async ({ page }, testInfo) => {
    const sid = `e2e-checkout-empty-${Date.now()}`

    const result = await captureTextSSE(page, '幫我結帳', sid)

    const assertions = [
      ...assertNoError(result),
      {
        name: '回應提示先點餐（不 crash）',
        passed: result.ttsAudioBase64.length > 0 || !!result.ttsText,
        detail: `ttsText：${result.ttsText}`,
      },
      {
        name: '未觸發 order_complete',
        passed: !result.events.some(e => e.event === 'order_complete'),
        detail: '空購物車不應完成訂單',
      },
    ]

    await attachSSEReport(testInfo, result, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })

  test('結帳後外帶 → dine_type = take-out', async ({ page }, testInfo) => {
    const sid = `e2e-checkout-takeout-${Date.now()}`

    await captureTextSSE(page, `我要一個${ITEM_1}`, sid)
    await captureTextSSE(page, '幫我結帳', sid)
    await captureTextSSE(page, '外帶', sid)
    const finalResult = await captureTextSSE(page, '付現金', sid)

    const orderComplete = finalResult.events.find(e => e.event === 'order_complete')

    const assertions = [
      ...assertNoError(finalResult),
      {
        name: 'dine_type = take-out',
        passed: orderComplete?.data?.dine_type === 'take-out',
        detail: `實際：${orderComplete?.data?.dine_type}`,
      },
    ]

    await attachSSEReport(testInfo, finalResult, assertions)

    for (const a of assertions) {
      expect(a.passed, `${a.name}: ${a.detail}`).toBe(true)
    }
  })
})
