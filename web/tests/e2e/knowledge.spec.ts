import { test, expect } from '@playwright/test'
import { apiAuth, deleteKnowledgeBase, findKnowledgeBase, login } from './helpers'

test('knowledge upload works from a non-document tab and reaches ready state', async ({ page, request }) => {
  const auth = await apiAuth(request)
  const kbName = `E2E 知识库 ${Date.now()}`
  const fileName = `e2e-upload-${Date.now()}.md`
  try {
    await login(page)
    await page.goto('/knowledge')
    await page.getByRole('button', { name: '新建知识库', exact: true }).click()
    const modal = page.locator('div.fixed.inset-0').filter({ hasText: '新建知识库' })
    await modal.getByPlaceholder('例如：产品资料').fill(kbName)
    await modal.getByRole('button', { name: '创建知识库', exact: true }).click()
    await expect(page.getByRole('heading', { name: kbName })).toBeVisible()

    // Switch away from the Documents tab, then use the header upload button.
    // This catches the previous bug where the file input was unmounted.
    await page.getByRole('button', { name: '设置', exact: true }).last().click()
    const chooserPromise = page.waitForEvent('filechooser')
    await page.getByRole('button', { name: '上传文档', exact: true }).click()
    const chooser = await chooserPromise
    await chooser.setFiles({
      name: fileName,
      mimeType: 'text/markdown',
      buffer: Buffer.from(`# ${fileName}\n\n退款会在 3 个工作日内原路返回。\n`, 'utf-8'),
    })

    const row = page.locator('div.card').filter({ hasText: fileName }).first()
    await expect(row).toBeVisible({ timeout: 20_000 })
    await expect(row.getByText('就绪', { exact: true })).toBeVisible({ timeout: 45_000 })
    await expect(row).toContainText('MD')

    await row.getByRole('button', { name: '分块', exact: true }).click()
    await expect(page.getByText(/分块 #1/)).toBeVisible({ timeout: 20_000 })
    await page.locator('div.fixed.inset-0').last().click({ position: { x: 5, y: 5 } })

    await page.getByRole('button', { name: '设置', exact: true }).last().click()
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: '删除知识库', exact: true }).click()
    await expect(page.getByRole('heading', { name: kbName })).toHaveCount(0)
  } finally {
    const kb = await findKnowledgeBase(request, auth, kbName)
    if (kb) await deleteKnowledgeBase(request, auth, kb.id)
  }
})