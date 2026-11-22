import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('plugin marketplace renders and installed calculator can be tested', async ({ page }) => {
  await login(page)
  await page.goto('/plugins')
  await expect(page.getByText('插件市场', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('文本统计', { exact: true }).first()).toBeVisible()

  const installedCalculator = page
    .locator('div.rounded-2xl')
    .filter({ hasText: '计算器' })
    .filter({ has: page.getByRole('button', { name: '测试', exact: true }) })
    .first()

  if (await installedCalculator.count()) {
    await installedCalculator.getByRole('button', { name: '测试', exact: true }).click()
    await expect(page.getByText(/测试「计算器」/)).toBeVisible()
    await page.locator('input[placeholder="输入测试值"]').fill('(1280 * 0.85) + 36')
    await page.getByRole('button', { name: '运行测试', exact: true }).click()
    await expect(page.getByText('1124', { exact: false })).toBeVisible({ timeout: 20_000 })
  }
})