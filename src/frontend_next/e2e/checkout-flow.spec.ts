import { test, expect } from '@playwright/test'

test.describe('結帳流程 — mock API', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/healthz', route => route.fulfill({ status: 200, body: 'ok' }))
    await page.route('**/api/checkout', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          order_number: '01',
          order_id: 'ORD-TEST-001',
          total: 50,
          dine_type: 'dine-in',
          payment_method: 'cash',
        }),
      })
    )
    await page.route('**/api/**', route => route.fulfill({ status: 200, body: '{}' }))
  })

  test('頁面載入後基本元素存在', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toBeVisible()
  })
})
