import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('workspace role matrix and member management are visible', async ({ page }) => {
  await login(page)
  await expect(page.getByText('所有者', { exact: true }).first()).toBeVisible()
  await page.goto('/settings')
  await page.getByRole('button', { name: '成员', exact: true }).click()
  await expect(page.getByText('你的角色', { exact: true })).toBeVisible()
  await expect(page.getByText('邀请成员', { exact: true })).toBeVisible()
  await expect(page.getByText('所有者角色不可在这里修改或移除。', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: '权限', exact: true }).click()
  await expect(page.getByText('Dify 风格工作空间角色', { exact: true })).toBeVisible()
  for (const role of ['所有者', '管理员', '编辑者', '运行者', '查看者']) {
    await expect(page.getByText(role, { exact: true }).first()).toBeVisible()
  }
  await expect(page.getByText('当前角色', { exact: true })).toBeVisible()
})