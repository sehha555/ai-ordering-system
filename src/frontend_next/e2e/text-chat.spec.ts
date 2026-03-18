import { test, expect } from '@playwright/test'

test.describe('文字對話 — mock SSE', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/healthz', route => route.fulfill({ status: 200, body: 'ok' }))
    await page.route('**/api/voice-chat', route => {
      const body = [
        'event: cart_update\n',
        'data: {"cart":[{"itemtype":"riceball","flavor":"鮪魚","quantity":1}]}\n\n',
        'event: ai_reply\n',
        'data: {"text":"已加入鮪魚飯糰"}\n\n',
        'event: done\n',
        'data: {}\n\n',
      ].join('')
      route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
        },
        body,
      })
    })
    await page.route('**/api/**', route => route.fulfill({ status: 200, body: '{}' }))
  })

  test('頁面載入後基本元素存在', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toBeVisible()
  })
})
