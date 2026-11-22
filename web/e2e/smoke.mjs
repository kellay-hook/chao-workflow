import { chromium } from 'playwright-core'

const base = process.env.FLOWMIND_WEB_URL || 'http://localhost:5180'
const chrome = process.env.CHROME_PATH
const browser = await chromium.launch({
  headless: true,
  executablePath: chrome || undefined,
  channel: chrome ? undefined : 'chrome',
  args: ['--no-sandbox'],
})
const errors = []
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', (error) => errors.push(String(error)))
page.on('console', (message) => {
  if (message.type() === 'error' && !message.text().includes('favicon')) errors.push(message.text())
})

try {
  await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
  await page.locator('input[type=email]').fill('demo@flowmind.dev')
  await page.locator('input[type=password]').fill('password123')
  await page.locator('form button[type=submit]').click()
  await page.waitForURL(`${base}/`, { timeout: 15000 })
  await page.waitForLoadState('networkidle')
  const dashboard = await page.locator('body').innerText()
  if (!dashboard.includes('DASHBOARD')) throw new Error('dashboard did not render overview text')

  const go = async (name) => {
    const link = page.getByRole('link', { name, exact: true })
    if ((await link.count()) === 0) {
      await page.locator('header button[aria-label="打开导航"]').click()
    }
    await page.getByRole('link', { name, exact: true }).click()
  }

  // Workflows: dedicated creation studio and webhook trigger panel
  await go('工作流')
  await page.waitForURL(`${base}/workflows`, { timeout: 15000 })
  await page.getByText('全部工作流', { exact: true }).waitFor({ timeout: 15000 })
  const workflowsText = await page.locator('body').innerText()
  for (const text of ['全部工作流', '新建工作流', '从模板开始']) {
    if (!workflowsText.includes(text)) throw new Error(`workflows page missing: ${text}`)
  }
  await page.goto(`${base}/workflows/new?mode=template`, { waitUntil: 'networkidle' })
  await page.getByText('创建新的工作流', { exact: true }).waitFor({ timeout: 15000 })
  const createText = await page.locator('body').innerText()
  for (const text of ['从模板创建', '空白画布', '导入 DSL', '复制已有', '工作流模板']) {
    if (!createText.includes(text)) throw new Error(`create workflow page missing: ${text}`)
  }
  await page.goto(`${base}/workflows`, { waitUntil: 'networkidle' })
  await page.locator('a[href^="/workflows/"]').filter({ hasText: 'Webhook 接收示例' }).first().click()
  await page.waitForTimeout(1200)
  const editorText = await page.locator('body').innerText()
  if (!/已发布 v\d+/.test(editorText)) throw new Error('published workflow status bar did not render')
  await page.getByRole('button', { name: '版本记录', exact: true }).click()
  await page.getByText('版本记录', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('当前运行版本', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '触发器', exact: true }).click()
  await page.getByText('触发方式 · Webhook', { exact: true }).waitFor({ timeout: 15000 })
  const triggerText = await page.locator('body').innerText()
  for (const text of ['已创建的 Webhook', '发送测试事件', '外部系统如何调用']) {
    if (!triggerText.includes(text)) throw new Error(`webhook panel missing: ${text}`)
  }
  await page.keyboard.press('Escape')

  // Knowledge: metadata editor, rerank controls and filter builder
  await go('知识库')
  await page.waitForURL(`${base}/knowledge`, { timeout: 15000 })
  await page.getByRole('button', { name: '检索测试', exact: true }).waitFor({ timeout: 15000 })
  await page.getByRole('button', { name: '元数据', exact: true }).first().waitFor({ timeout: 15000 })
  const knowledgeText = await page.locator('body').innerText()
  for (const text of ['检索测试', '元数据', '重解析']) {
    if (!knowledgeText.includes(text)) throw new Error(`knowledge page missing: ${text}`)
  }
  await page.getByRole('button', { name: '元数据', exact: true }).first().click()
  await page.getByText('文档元数据', { exact: true }).waitFor({ timeout: 10000 })
  const metadataDraft = await page.locator('textarea').first().inputValue()
  if (!metadataDraft.trim().startsWith('{')) throw new Error('metadata editor did not load JSON')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '检索测试', exact: true }).click()
  const searchText = await page.locator('body').innerText()
  for (const text of ['重排序', '元数据过滤', '添加条件']) {
    if (!searchText.includes(text)) throw new Error(`search panel missing: ${text}`)
  }
  await page.getByRole('button', { name: /添加条件/ }).click()
  if ((await page.getByPlaceholder('字段，例如 category').count()) !== 1) {
    throw new Error('metadata filter row did not render')
  }

  // Tools: OAuth connection form and callback banners
  await go('工具 / MCP')
  await page.waitForURL(`${base}/tools`, { timeout: 15000 })
  await page.getByText('新建 HTTP 工具', { exact: true }).waitFor({ timeout: 15000 })
  const toolsText = await page.locator('body').innerText()
  for (const text of ['新建 HTTP 工具', '已注册工具', 'MCP 服务', 'OAuth 连接']) {
    if (!toolsText.includes(text)) throw new Error(`tools page missing: ${text}`)
  }
  await page.getByRole('button', { name: /MCP 服务/ }).click()
  await page.getByText('新建 MCP 服务', { exact: true }).waitFor({ timeout: 15000 })
  const mcpText = await page.locator('body').innerText()
  for (const text of ['FlowMind 内置演示 MCP', '发现工具']) {
    if (!mcpText.includes(text)) throw new Error(`mcp tab missing: ${text}`)
  }
  await page.getByRole('button', { name: /OAuth 连接/ }).click()
  await page.getByText('新建 OAuth 连接', { exact: true }).waitFor({ timeout: 15000 })
  await page.goto(`${base}/tools?oauth=success`, { waitUntil: 'networkidle' })
  if (!(await page.locator('body').innerText()).includes('OAuth 授权成功')) {
    throw new Error('oauth success banner did not render')
  }
  await page.goto(`${base}/tools?oauth=error&message=denied`, { waitUntil: 'networkidle' })
  if (!(await page.locator('body').innerText()).includes('denied')) {
    throw new Error('oauth error banner did not render')
  }

  // Plugins: marketplace and installed plugins render
  await go('插件')
  await page.waitForURL(`${base}/plugins`, { timeout: 15000 })
  await page.getByText('插件市场', { exact: true }).first().waitFor({ timeout: 15000 })
  await page.getByText('文本统计', { exact: true }).first().waitFor({ timeout: 15000 })
  const pluginsText = await page.locator('body').innerText()
  for (const text of ['已安装插件', '插件市场', '文本统计', 'HTTP 连接器']) {
    if (!pluginsText.includes(text)) throw new Error(`plugins page missing: ${text}`)
  }

  // Agents: persistent session controls
  await go('Agent')
  await page.waitForURL(`${base}/agents`, { timeout: 15000 })
  await page.getByText('Agent 智能体', { exact: true }).waitFor({ timeout: 15000 })
  await page.getByRole('button', { name: '调试', exact: true }).click()
  await page.getByText('对话轨迹', { exact: true }).waitFor({ timeout: 15000 })
  const agentsText = await page.locator('body').innerText()
  for (const text of ['对话轨迹', '新对话', '运行调试']) {
    if (!agentsText.includes(text)) throw new Error(`agents page missing: ${text}`)
  }

  const context = await browser.newContext()
  const register = await context.newPage()
  const email = `browser${Date.now()}@example.com`
  await register.goto(`${base}/register`, { waitUntil: 'networkidle' })
  const inputs = register.locator('form input')
  await inputs.nth(0).fill('Browser User')
  await inputs.nth(1).fill(email)
  await inputs.nth(2).fill('password123')
  await inputs.nth(3).fill('Browser Lab')
  await register.locator('form button[type=submit]').click()
  await register.waitForURL(`${base}/`, { timeout: 15000 })
  await register.waitForLoadState('networkidle')
  const registered = await register.locator('body').innerText()
  if (!registered.includes('DASHBOARD')) throw new Error('registration did not auto-login')
  if (errors.length) throw new Error(`browser errors: ${errors.join(' | ')}`)
  console.log('E2E smoke passed')
} finally {
  await browser.close()
}
