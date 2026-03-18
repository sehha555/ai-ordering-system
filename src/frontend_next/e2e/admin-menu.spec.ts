import { test, expect } from '@playwright/test'

// Layer 3：需要 backend，本地手動跑
test.describe('Admin 菜單管理 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend')

  test('進入 admin/menu 頁面', async ({ page }) => {
    await page.goto('/admin/menu')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toBeVisible()
  })
})
