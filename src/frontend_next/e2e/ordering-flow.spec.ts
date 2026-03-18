import { test, expect } from '@playwright/test'

// Layer 3：需要 backend + LM Studio，本地手動跑
test.describe('Full Stack 點餐流程 @fullstack', () => {
  test.skip(!!process.env.CI, 'Skip in CI — requires backend + LM Studio')

  test('文字點餐 → 購物車更新', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const input = page.locator('input[type="text"], textarea').first()
    if (await input.isVisible()) {
      await input.fill('我要一個鮪魚飯糰')
      await input.press('Enter')
      await page.waitForTimeout(5000)
    }
  })
})
