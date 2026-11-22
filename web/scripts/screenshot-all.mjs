import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const base = process.env.FLOWMIND_WEB_URL || 'http://localhost:5180'
const webRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const outDir = process.env.SCREENSHOT_DIR || path.resolve(webRoot, '..', 'screenshots')
const desktopViewport = { width: 1440, height: 1000 }
const mobileViewport = { width: 390, height: 844 }
const failures = []

await fs.mkdir(outDir, { recursive: true })

const browser = await chromium.launch({
  headless: true,
  channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
})

async function stabilize(page) {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(900)
}

async function shot(page, name) {
  try {
    await stabilize(page)
    const file = path.join(outDir, `${name}.png`)
    await page.screenshot({ path: file, fullPage: true })
    console.log(`✓ ${name}.png`)
  } catch (error) {
    failures.push(name)
    console.error(`✗ ${name}:`, error instanceof Error ? error.message : error)
  }
}

async function login(page) {
  await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
  await page.locator('input[type=email]').fill('demo@flowmind.dev')
  await page.locator('input[type=password]').fill('password123')
  await page.locator('form button[type=submit]').click()
  await page.waitForURL(`${base}/`, { timeout: 20000 })
  await page.getByRole('heading', { name: /你好，/ }).waitFor({ timeout: 20000 })
}

async function captureDesktop() {
  const page = await browser.newPage({ viewport: desktopViewport })
  const errors = []
  page.on('pageerror', (error) => errors.push(String(error)))
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('favicon')) errors.push(message.text())
  })

  await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-01-login')
  await login(page)
  await shot(page, 'desktop-02-dashboard')

  await page.goto(`${base}/workflows`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-03-workflows')

  await page.goto(`${base}/workflows/new?mode=template`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-04-workflow-create')

  await page.goto(`${base}/workflows`, { waitUntil: 'networkidle' })
  await page.locator('a[href^="/workflows/"]').first().click()
  await page.waitForTimeout(1400)
  await shot(page, 'desktop-05-workflow-editor')

  await page.goto(`${base}/runs`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-06-runs')
  const runLink = page.locator('tbody a[href^="/runs/"]').first()
  if (await runLink.count()) {
    await runLink.click()
    await page.waitForTimeout(1400)
    await shot(page, 'desktop-07-run-detail')
  }

  await page.goto(`${base}/approvals`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-08-approvals')

  await page.goto(`${base}/knowledge`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-09-knowledge-documents')
  const searchTab = page.getByRole('button', { name: '检索测试', exact: true })
  if (await searchTab.count()) {
    await searchTab.first().click()
    await shot(page, 'desktop-10-knowledge-search')
  }

  await page.goto(`${base}/agents`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-11-agents-config')
  const debugTab = page.getByRole('button', { name: '调试', exact: true })
  if (await debugTab.count()) {
    await debugTab.first().click()
    await shot(page, 'desktop-12-agents-debug')
  }

  await page.goto(`${base}/tools`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-13-tools')
  const mcpTab = page.getByRole('button', { name: /MCP 服务/ })
  if (await mcpTab.count()) {
    await mcpTab.first().click()
    await shot(page, 'desktop-14-tools-mcp')
  }
  const oauthTab = page.getByRole('button', { name: /OAuth 连接/ })
  if (await oauthTab.count()) {
    await oauthTab.first().click()
    await shot(page, 'desktop-15-tools-oauth')
  }

  await page.goto(`${base}/plugins`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-16-plugins')

  await page.goto(`${base}/settings`, { waitUntil: 'networkidle' })
  await shot(page, 'desktop-17-settings-models')
  const membersTab = page.getByRole('button', { name: '成员', exact: true })
  if (await membersTab.count()) {
    await membersTab.first().click()
    await shot(page, 'desktop-18-settings-members')
  }
  const permissionsTab = page.getByRole('button', { name: '权限', exact: true })
  if (await permissionsTab.count()) {
    await permissionsTab.first().click()
    await shot(page, 'desktop-19-settings-permissions')
  }

  if (errors.length) failures.push(`desktop console errors: ${errors.join(' | ')}`)
  await page.close()
}

async function captureMobile() {
  const page = await browser.newPage({ viewport: mobileViewport })
  await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
  await shot(page, 'mobile-01-login')
  await login(page)
  await shot(page, 'mobile-02-dashboard')

  for (const [route, name] of [
    ['/workflows', 'mobile-03-workflows'],
    ['/knowledge', 'mobile-04-knowledge'],
    ['/agents', 'mobile-05-agents'],
    ['/tools', 'mobile-06-tools'],
    ['/plugins', 'mobile-07-plugins'],
  ]) {
    await page.goto(`${base}${route}`, { waitUntil: 'networkidle' })
    await shot(page, name)
  }
  await page.close()
}

try {
  await captureDesktop()
  await captureMobile()
} finally {
  await browser.close()
}

console.log(`\n截图目录: ${outDir}`)
if (failures.length) {
  console.error(`失败项: ${failures.join(', ')}`)
  process.exitCode = 1
} else {
  console.log('全部页面截图完成。')
}