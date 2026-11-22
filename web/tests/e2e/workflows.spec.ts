import { test, expect } from '@playwright/test'
import { apiAuth, deleteWorkflow, login } from './helpers'

test('create a blank workflow, publish it and inspect version history', async ({ page, request }) => {
  const auth = await apiAuth(request)
  const name = `E2E 发布测试 ${Date.now()}`
  let workflowId = ''
  try {
    await login(page)
    await page.goto('/workflows/new?mode=blank')
    await expect(page.getByText('创建新的工作流', { exact: true })).toBeVisible()
    await page.locator('aside input').first().fill(name)
    await page.getByRole('button', { name: /创建并打开画布/ }).click()
    await page.waitForURL(/\/workflows\/[0-9a-f-]+$/)
    workflowId = page.url().split('/').pop() || ''

    await expect(page.getByText('当前是草稿 · 尚未发布', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '立即发布', exact: true }).click()
    await expect(page.getByText('已发布 v1 · 可运行', { exact: true })).toBeVisible({ timeout: 30_000 })

    await page.getByRole('button', { name: '版本记录', exact: true }).click()
    await expect(page.getByText('版本记录', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('当前运行版本', { exact: true })).toBeVisible()
    await expect(page.getByText('v1', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '关闭', exact: true }).click()
  } finally {
    if (workflowId) await deleteWorkflow(request, auth, workflowId)
  }
})

test('webhook demo can dispatch a run from the editor', async ({ page }) => {
  await login(page)
  await page.goto('/workflows')
  await page.locator('a[href^="/workflows/"]').filter({ hasText: 'Webhook 接收示例' }).first().click()
  await expect(page.getByText(/已发布 v\d+ · 可运行/)).toBeVisible()
  await page.getByRole('button', { name: '触发器', exact: true }).click()
  await expect(page.getByText('触发方式 · Webhook', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '测试', exact: true }).first().click()
  await expect(page.getByText('测试事件已触发', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/查看运行/)).toBeVisible()
})