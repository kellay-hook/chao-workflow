import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('demo user can login and reach dashboard', async ({ page }) => {
  await login(page)
  await expect(page.getByRole('heading', { name: /你好，Demo Owner/ })).toBeVisible()
  await expect(page.getByText('推荐操作路径', { exact: true })).toBeVisible()
  await expect(page.getByText('最近运行', { exact: true })).toBeVisible()
})