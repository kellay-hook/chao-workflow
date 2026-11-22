import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('MCP demo tools can be discovered, added and tested', async ({ page }) => {
  await login(page)
  await page.goto('/tools')
  await page.getByRole('button', { name: /MCP 服务/ }).click()

  if ((await page.getByText('FlowMind 内置演示 MCP', { exact: true }).count()) === 0) {
    await page.getByRole('button', { name: /使用内置演示/ }).click()
    await page.getByRole('button', { name: '添加服务', exact: true }).click()
  }
  await expect(page.getByText('FlowMind 内置演示 MCP', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '发现工具', exact: true }).first().click()
  await expect(page.getByText('echo', { exact: true }).first()).toBeVisible({ timeout: 30_000 })

  const echoMcpRow = page.locator('div.rounded-xl.border').filter({ hasText: 'echo' }).first()
  const addButton = echoMcpRow.getByRole('button', { name: /添加为工具/ })
  if (await addButton.count()) await addButton.click()

  await page.getByRole('button', { name: /^工具\s+\d+$/ }).click()
  const echoTool = page.locator('div.rounded-2xl.border').filter({ hasText: 'echo' }).first()
  await expect(echoTool).toBeVisible()
  await echoTool.getByRole('button', { name: '测试', exact: true }).click()

  const testTextarea = page.locator('div.fixed.inset-0 textarea').first()
  await testTextarea.fill(JSON.stringify({ message: 'hello from playwright' }))
  await page.getByRole('button', { name: '运行测试', exact: true }).click()
  await expect(page.getByText('hello from playwright', { exact: false })).toBeVisible({ timeout: 30_000 })
})