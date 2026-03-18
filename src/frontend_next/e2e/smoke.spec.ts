import { test, expect } from '@playwright/test'

test.describe('Smoke — 頁面載入', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/**', route => route.fulfill({ status: 200, body: '{}' }))
    await page.route('**/healthz', route => route.fulfill({ status: 200, body: 'ok' }))
  })

  test('首頁可載入', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('body')).toBeVisible()
  })

  test('頁面有 canvas（AudioVisualizer）', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('canvas').first()).toBeVisible()
  })
})
