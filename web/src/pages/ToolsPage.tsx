import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Globe,
  KeyRound,
  Link2,
  Loader2,
  Play,
  PlugZap,
  Plus,
  Puzzle,
  RefreshCw,
  Server,
  ShieldCheck,
  Trash2,
  Wrench,
  X,
} from 'lucide-react'
import { resourceApi } from '../api'
import type { McpServer, McpTool, OAuthConnection, Tool } from '../types'
import { Button, Callout, EmptyState, Field, GuideSteps, JsonBlock, PageHeader } from '../components/ui'
import { useCan } from '../components/permissions'
import JsonViewer from '../components/JsonViewer'

type Tab = 'tools' | 'mcp' | 'oauth'

const oauthStatus: Record<string, string> = { connected: '已连接', disconnected: '未授权', error: '授权失败' }
const oauthStatusStyle: Record<string, string> = {
  connected: 'bg-emerald-50 text-emerald-700',
  disconnected: 'bg-slate-100 text-slate-600',
  error: 'bg-rose-50 text-rose-700',
}
const riskLabels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险', deny: '禁止' }
const riskStyles: Record<string, string> = {
  low: 'bg-sky-50 text-sky-700',
  medium: 'bg-amber-50 text-amber-700',
  high: 'bg-rose-50 text-rose-700',
  deny: 'bg-slate-100 text-slate-600',
}

function exampleInputs(schema: Record<string, any>): Record<string, any> {
  const properties = (schema?.properties || {}) as Record<string, any>
  const result: Record<string, any> = {}
  for (const [key, value] of Object.entries(properties)) {
    if (value?.default !== undefined) result[key] = value.default
    else if (value?.type === 'number' || value?.type === 'integer') result[key] = 0
    else if (value?.type === 'boolean') result[key] = false
    else if (value?.type === 'object') result[key] = {}
    else if (value?.type === 'array') result[key] = []
    else result[key] = ''
  }
  return result
}

export default function ToolsPage() {
  const canWriteTools = useCan('tool.write')
  const canTestTools = useCan('tool.test')
  const [tab, setTab] = useState<Tab>('tools')
  const [tools, setTools] = useState<Tool[]>([])
  const [connections, setConnections] = useState<OAuthConnection[]>([])
  const [servers, setServers] = useState<McpServer[]>([])
  const [serverTools, setServerTools] = useState<Record<string, McpTool[]>>({})
  const [expandedServer, setExpandedServer] = useState('')
  const [form, setForm] = useState({ name: '', method: 'POST', url: '', risk_level: 'medium', oauth_connection_id: '' })
  const [oauthForm, setOauthForm] = useState({ name: '', auth_url: '', token_url: '', client_id: '', client_secret: '', scopes: '', token_auth_method: 'client_secret_post' })
  const [mcpForm, setMcpForm] = useState({ name: '', transport: 'streamable_http', url: '', headers: '{}' })
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [addingTool, setAddingTool] = useState('')
  const [testTarget, setTestTarget] = useState<Tool | null>(null)
  const [testInputs, setTestInputs] = useState('{}')
  const [testResult, setTestResult] = useState<any>(null)
  const [testError, setTestError] = useState('')
  const [params] = useSearchParams()

  const load = async () => {
    const [toolData, connectionData, serverData] = await Promise.all([
      resourceApi.tools(),
      resourceApi.oauthConnections(),
      resourceApi.mcpServers(),
    ])
    setTools(toolData)
    setConnections(connectionData)
    setServers(serverData)
  }

  useEffect(() => {
    void load().catch((err) => setError(err.message))
    const oauth = params.get('oauth')
    if (oauth === 'success') setMessage('OAuth 授权成功，可以创建或测试工具了')
    if (oauth === 'error') setError(params.get('message') || 'OAuth 授权失败')
  }, [])

  const connectionNames = useMemo(() => new Map(connections.map((connection) => [connection.id, connection.name])), [connections])
  const mcpToolNames = useMemo(() => new Set(tools.filter((tool) => tool.type === 'mcp').map((tool) => tool.name)), [tools])

  const loadServerTools = async (serverId: string) => {
    try {
      const data = await resourceApi.mcpServerTools(serverId)
      setServerTools((current) => ({ ...current, [serverId]: data }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 MCP 工具失败')
    }
  }

  const discover = async (server: McpServer) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await resourceApi.discoverMcp(server.id)
      setServerTools((current) => ({ ...current, [server.id]: data }))
      setExpandedServer(server.id)
      setMessage(`已发现 ${data.length} 个 MCP 工具`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'MCP 工具发现失败')
    } finally {
      setBusy(false)
    }
  }

  const toggleServer = async (server: McpServer) => {
    if (expandedServer === server.id) {
      setExpandedServer('')
      return
    }
    setExpandedServer(server.id)
    if (!serverTools[server.id]) await loadServerTools(server.id)
  }

  const addMcpTool = async (server: McpServer, mcpTool: McpTool) => {
    setAddingTool(mcpTool.id)
    setError('')
    try {
      await resourceApi.addMcpTool(server.id, mcpTool.id)
      setMessage(`「${mcpTool.name}」已添加为工具，可以绑定到 Agent`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加 MCP 工具失败')
    } finally {
      setAddingTool('')
    }
  }

  const openTest = (tool: Tool) => {
    setTestTarget(tool)
    setTestInputs(JSON.stringify(exampleInputs(tool.input_schema || {}), null, 2))
    setTestResult(null)
    setTestError('')
  }

  const runTest = async () => {
    if (!testTarget) return
    setBusy(true)
    setTestError('')
    setTestResult(null)
    try {
      const response = await resourceApi.testTool(testTarget.id, JSON.parse(testInputs || '{}'))
      setTestResult(response.result)
    } catch (err) {
      setTestError(err instanceof Error ? err.message : '工具测试失败')
    } finally {
      setBusy(false)
    }
  }

  const removeTool = async (tool: Tool) => {
    if (tool.type === 'plugin') {
      setError('插件工具请在「插件」页面卸载，避免插件与工具状态不一致。')
      return
    }
    if (!window.confirm(`删除工具「${tool.name}」？`)) return
    try {
      await resourceApi.deleteTool(tool.id)
      await load()
      setMessage('工具已删除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  const tabs: { id: Tab; label: string; count: number; icon: typeof Wrench }[] = [
    { id: 'tools', label: '工具', count: tools.length, icon: Wrench },
    { id: 'mcp', label: 'MCP 服务', count: servers.length, icon: Server },
    { id: 'oauth', label: 'OAuth 连接', count: connections.length, icon: KeyRound },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Tools & MCP"
        title="工具 / MCP"
        description="把 HTTP API、插件和 MCP 服务变成 Agent 可调用的工具；先测试，再绑定到 Agent。"
        icon={Boxes}
        actions={
          <>
            <Link to="/plugins" className="btn-secondary"><Puzzle size={15} /> 插件市场</Link>
            <Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /> 刷新</Button>
          </>
        }
      />

      <GuideSteps
        steps={[
          { title: '选择接入方式', description: 'HTTP 工具、MCP 服务或插件，按外部系统能力选择。' },
          { title: '配置连接', description: '填写 URL、认证方式或 OAuth 连接。' },
          { title: '发现并测试', description: 'MCP 先发现工具，HTTP/插件直接运行一次测试。' },
          { title: '绑定 Agent', description: '在 Agent 配置中勾选工具，中高风险调用会进入审批。' },
        ]}
      />

      {error && <Callout tone="error">{error}</Callout>}
      {message && <Callout tone="success">{message}</Callout>}
      {!canWriteTools && <Callout tone="info" title="只读模式">当前角色可以查看工具、MCP 服务和授权状态，但不能创建、修改或发现工具。</Callout>}

      <div className="flex w-fit flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm">
        {tabs.map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-[12px] font-semibold transition ${tab === item.id ? 'bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-sm shadow-indigo-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'}`}
            >
              <Icon size={14} /> {item.label}
              <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${tab === item.id ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'}`}>{item.count}</span>
            </button>
          )
        })}
      </div>

      {tab === 'tools' && (
        <div className={`grid gap-5 ${canWriteTools ? 'xl:grid-cols-[380px_minmax(0,1fr)]' : ''}`}>
          {canWriteTools && <section className="card h-fit p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 section-title"><Wrench size={16} className="text-indigo-500" /> 新建 HTTP 工具</div>
                <div className="section-desc">对外部 HTTP API 做一层函数封装，供 Agent 调用。</div>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              <Field label="工具名称" hint="建议使用英文函数名，例如 create_ticket。">
                <input className="input" placeholder="create_ticket" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="请求方法">
                  <select className="input" value={form.method} onChange={(event) => setForm({ ...form, method: event.target.value })}>
                    {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((method) => <option key={method}>{method}</option>)}
                  </select>
                </Field>
                <Field label="风险级别">
                  <select className="input" value={form.risk_level} onChange={(event) => setForm({ ...form, risk_level: event.target.value })}>
                    <option value="low">低风险</option>
                    <option value="medium">中风险 · 需审批</option>
                    <option value="high">高风险 · 需审批</option>
                    <option value="deny">禁止执行</option>
                  </select>
                </Field>
              </div>
              <Field label="请求 URL">
                <input className="input" placeholder="https://api.example.com/tickets" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} />
              </Field>
              <Field label="OAuth 连接" hint="需要登录的外部服务请选择已授权的连接。">
                <select className="input" value={form.oauth_connection_id} onChange={(event) => setForm({ ...form, oauth_connection_id: event.target.value })}>
                  <option value="">不使用 OAuth</option>
                  {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}（{oauthStatus[connection.status] || connection.status}）</option>)}
                </select>
              </Field>
              <Button
                disabled={busy || !form.name.trim() || !form.url.trim()}
                onClick={async () => {
                  setBusy(true)
                  setError('')
                  setMessage('')
                  try {
                    await resourceApi.createTool({
                      name: form.name,
                      type: 'http',
                      description: `HTTP ${form.method} ${form.url}`,
                      input_schema: { type: 'object', properties: {} },
                      config: { method: form.method, url: form.url, timeout_sec: 30, oauth_connection_id: form.oauth_connection_id || undefined },
                      risk_level: form.risk_level,
                      enabled: true,
                    })
                    setForm({ ...form, name: '', url: '' })
                    setMessage('HTTP 工具已创建，可以立即测试')
                    await load()
                  } catch (err) {
                    setError(err instanceof Error ? err.message : '创建失败')
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                <Plus size={15} /> 创建工具
              </Button>
            </div>
          </section>}

          <section className="card p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2 section-title"><Link2 size={16} className="text-indigo-500" /> 已注册工具</div>
                <div className="section-desc">HTTP、MCP 与插件工具都会出现在这里；插件工具请在插件页管理。</div>
              </div>
              <span className="badge bg-slate-100 text-slate-600">{tools.length} 个</span>
            </div>
            <div className="mt-4 space-y-3">
              {tools.map((tool) => (
                <div key={tool.id} className="rounded-2xl border border-slate-200 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-semibold text-slate-800">{tool.name}</span>
                        <span className="badge bg-slate-100 text-slate-600">{tool.type}</span>
                        <span className={`badge ${riskStyles[tool.risk_level] || riskStyles.medium}`}>{riskLabels[tool.risk_level] || tool.risk_level}</span>
                        {Boolean(tool.config?.oauth_connection_id) && <span className="badge bg-violet-50 text-violet-700"><KeyRound size={11} /> {connectionNames.get(String(tool.config.oauth_connection_id)) || 'OAuth'}</span>}
                      </div>
                      <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{tool.description || '暂无描述'}</div>
                    </div>
                    <div className="flex items-center gap-1">
                      {canTestTools && <Button variant="secondary" className="h-8 px-2.5 text-[11px]" onClick={() => openTest(tool)}><Play size={12} /> 测试</Button>}
                      {tool.type === 'plugin' ? (
                        <Link to="/plugins" className="btn h-8 px-2 text-[11px] text-indigo-600 hover:bg-indigo-50"><Puzzle size={12} /> 插件页</Link>
                      ) : (
                        <>{canWriteTools && <Button variant="ghost" className="h-8 px-2 text-rose-600" onClick={() => void removeTool(tool)}><Trash2 size={13} /></Button>}</>
                      )}
                    </div>
                  </div>
                  <details className="mt-3 rounded-xl bg-slate-50/80">
                    <summary className="cursor-pointer list-none px-3 py-2 text-[10px] font-semibold text-slate-500">查看配置 JSON</summary>
                    <div className="border-t border-slate-200 p-2"><JsonBlock value={tool.config} /></div>
                  </details>
                </div>
              ))}
              {!tools.length && <EmptyState title="还没有工具" hint="创建一个 HTTP 工具，或到 MCP 服务页发现工具。" icon={Wrench} />}
            </div>
          </section>
        </div>
      )}

      {tab === 'mcp' && (
        <div className={`grid gap-5 ${canWriteTools ? 'xl:grid-cols-[380px_minmax(0,1fr)]' : ''}`}>
          {canWriteTools && <section className="card h-fit p-5">
            <div className="flex items-center gap-2 section-title"><Server size={16} className="text-indigo-500" /> 新建 MCP 服务</div>
            <div className="section-desc">支持 Streamable HTTP / SSE。连接后可发现服务端工具并逐个添加。</div>
            <div className="mt-4 space-y-3">
              <Field label="服务名称">
                <input className="input" placeholder="例如：内部知识 MCP" value={mcpForm.name} onChange={(event) => setMcpForm({ ...mcpForm, name: event.target.value })} />
              </Field>
              <Field label="传输方式">
                <select className="input" value={mcpForm.transport} onChange={(event) => setMcpForm({ ...mcpForm, transport: event.target.value })}>
                  <option value="streamable_http">Streamable HTTP</option>
                  <option value="sse">SSE</option>
                </select>
              </Field>
              <Field label="MCP URL" hint="示例：http://host:port/mcp">
                <input className="input" placeholder="https://mcp.example.com/mcp" value={mcpForm.url} onChange={(event) => setMcpForm({ ...mcpForm, url: event.target.value })} />
              </Field>
              <Field label="请求头 JSON" hint="可选，例如 Authorization。">
                <textarea className="input min-h-20 font-mono text-xs" value={mcpForm.headers} onChange={(event) => setMcpForm({ ...mcpForm, headers: event.target.value })} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={busy || !mcpForm.name.trim() || !mcpForm.url.trim()}
                  onClick={async () => {
                    setBusy(true)
                    setError('')
                    try {
                      const headers = JSON.parse(mcpForm.headers || '{}')
                      await resourceApi.createMcpServer({ ...mcpForm, headers })
                      setMcpForm({ name: '', transport: 'streamable_http', url: '', headers: '{}' })
                      setMessage('MCP 服务已添加，点击「发现工具」读取服务端能力')
                      await load()
                    } catch (err) {
                      setError(err instanceof Error ? err.message : '添加 MCP 服务失败')
                    } finally {
                      setBusy(false)
                    }
                  }}
                >
                  <Plus size={15} /> 添加服务
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setMcpForm({ name: 'FlowMind 内置演示 MCP', transport: 'streamable_http', url: `${window.location.origin}/api/v1/mcp/demo`, headers: '{}' })}
                >
                  <PlugZap size={15} /> 使用内置演示
                </Button>
              </div>
            </div>
          </section>}

          <section className="card p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2 section-title"><Server size={16} className="text-indigo-500" /> MCP 服务</div>
                <div className="section-desc">发现工具后可一键添加为 Agent 工具。</div>
              </div>
              <span className="badge bg-slate-100 text-slate-600">{servers.length} 个</span>
            </div>
            <div className="mt-4 space-y-3">
              {servers.map((server) => (
                <div key={server.id} className="rounded-2xl border border-slate-200">
                  <div className="flex flex-wrap items-start justify-between gap-3 p-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-semibold text-slate-800">{server.name}</span>
                        <span className="badge bg-indigo-50 text-indigo-700">{server.transport}</span>
                        <span className={`badge ${server.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{server.enabled ? '已启用' : '已禁用'}</span>
                      </div>
                      <div className="mt-1 break-all font-mono text-[10px] text-slate-400">{server.url}</div>
                      <div className="mt-1 text-[10px] text-slate-400">{server.last_discovered_at ? `上次发现：${new Date(server.last_discovered_at).toLocaleString()}` : '尚未发现工具'}</div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {canWriteTools && <Button variant="secondary" className="h-8 px-2.5 text-[11px]" disabled={busy} onClick={() => void discover(server)}><RefreshCw size={12} /> 发现工具</Button>}
                      <Button variant="ghost" className="h-8 px-2 text-[11px]" onClick={() => void toggleServer(server)}>{expandedServer === server.id ? <ChevronDown size={13} /> : <ChevronRight size={13} />} 工具</Button>
                      {canWriteTools && <Button variant="ghost" className="h-8 px-2 text-rose-600" onClick={async () => { if (!window.confirm(`删除 MCP 服务「${server.name}」？`)) return; await resourceApi.deleteMcpServer(server.id); await load(); setMessage('MCP 服务已删除') }}><Trash2 size={13} /></Button>}
                    </div>
                  </div>
                  {expandedServer === server.id && (
                    <div className="border-t border-slate-100 bg-slate-50/60 p-3">
                      <div className="space-y-2">
                        {(serverTools[server.id] || []).map((mcpTool) => {
                          const exists = mcpToolNames.has(mcpTool.name)
                          return (
                            <div key={mcpTool.id} className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2"><span className="font-mono text-[12px] font-semibold text-slate-800">{mcpTool.name}</span><span className={`badge ${riskStyles[mcpTool.risk_level] || riskStyles.medium}`}>{riskLabels[mcpTool.risk_level] || mcpTool.risk_level}</span></div>
                                <div className="mt-1 text-[11px] text-slate-500">{mcpTool.description || '暂无描述'}</div>
                                <details className="mt-2 rounded-lg bg-slate-50">
                                  <summary className="cursor-pointer list-none px-2 py-1.5 text-[10px] font-semibold text-slate-400">查看参数 Schema</summary>
                                  <div className="border-t border-slate-200 p-2"><JsonBlock value={mcpTool.input_schema} /></div>
                                </details>
                              </div>
                              {canWriteTools && <Button variant="secondary" className="h-8 px-2.5 text-[11px]" disabled={exists || addingTool === mcpTool.id} onClick={() => void addMcpTool(server, mcpTool)}>
                                {exists ? <><CheckCircle2 size={12} /> 已添加</> : addingTool === mcpTool.id ? <><Loader2 size={12} className="animate-spin" /> 添加中…</> : <><Plus size={12} /> 添加为工具</>}
                              </Button>}
                            </div>
                          )
                        })}
                        {!(serverTools[server.id] || []).length && <div className="py-5 text-center text-[11px] text-slate-400">还没有发现工具。点击上方「发现工具」。</div>}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {!servers.length && <EmptyState title="还没有 MCP 服务" hint="可以使用内置演示 MCP 快速体验发现工具与调用链路。" icon={Server} action={<Button variant="secondary" onClick={() => setMcpForm({ name: 'FlowMind 内置演示 MCP', transport: 'streamable_http', url: `${window.location.origin}/api/v1/mcp/demo`, headers: '{}' })}><PlugZap size={14} /> 填入演示服务器</Button>} />}
            </div>
          </section>
        </div>
      )}

      {tab === 'oauth' && (
        <div className={`grid gap-5 ${canWriteTools ? 'xl:grid-cols-2' : ''}`}>
          {canWriteTools && <section className="card p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 section-title"><KeyRound size={16} className="text-indigo-500" /> 新建 OAuth 连接</div>
                <div className="section-desc">适用于需要登录的 HTTP 服务。Token 会加密保存。</div>
              </div>
              <span className="badge bg-indigo-50 text-indigo-700">Authorization Code</span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2"><Field label="连接名称"><input className="input" placeholder="例如：GitHub、企业 CRM" value={oauthForm.name} onChange={(event) => setOauthForm({ ...oauthForm, name: event.target.value })} /></Field></div>
              <div className="sm:col-span-2"><Field label="Authorization URL"><input className="input" placeholder="https://provider.com/oauth/authorize" value={oauthForm.auth_url} onChange={(event) => setOauthForm({ ...oauthForm, auth_url: event.target.value })} /></Field></div>
              <div className="sm:col-span-2"><Field label="Token URL"><input className="input" placeholder="https://provider.com/oauth/token" value={oauthForm.token_url} onChange={(event) => setOauthForm({ ...oauthForm, token_url: event.target.value })} /></Field></div>
              <Field label="Client ID"><input className="input" placeholder="Client ID" value={oauthForm.client_id} onChange={(event) => setOauthForm({ ...oauthForm, client_id: event.target.value })} /></Field>
              <Field label="Token 认证方式">
                <select className="input" value={oauthForm.token_auth_method} onChange={(event) => setOauthForm({ ...oauthForm, token_auth_method: event.target.value })}>
                  <option value="client_secret_post">Secret 放在请求体</option>
                  <option value="client_secret_basic">Secret 使用 HTTP Basic</option>
                </select>
              </Field>
              <Field label="Client Secret"><input className="input" type="password" placeholder="Client Secret" value={oauthForm.client_secret} onChange={(event) => setOauthForm({ ...oauthForm, client_secret: event.target.value })} /></Field>
              <Field label="Scopes" hint="空格或逗号分隔。"><input className="input" placeholder="read:data write:data" value={oauthForm.scopes} onChange={(event) => setOauthForm({ ...oauthForm, scopes: event.target.value })} /></Field>
            </div>
            <div className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-[11px] text-slate-500">回调地址：<code className="rounded bg-white px-1.5 py-0.5 font-mono text-[10px] ring-1 ring-slate-200">/api/v1/oauth/callback</code></div>
            <Button
              className="mt-4"
              disabled={busy || !oauthForm.name.trim() || !oauthForm.auth_url.trim() || !oauthForm.token_url.trim() || !oauthForm.client_id.trim() || !oauthForm.client_secret.trim()}
              onClick={async () => {
                setBusy(true)
                setError('')
                try {
                  await resourceApi.createOAuthConnection({ ...oauthForm, scopes: oauthForm.scopes.split(/[\s,]+/).filter(Boolean) })
                  setOauthForm({ name: '', auth_url: '', token_url: '', client_id: '', client_secret: '', scopes: '', token_auth_method: 'client_secret_post' })
                  setMessage('OAuth 连接已创建，下一步点击「授权」')
                  await load()
                } catch (err) {
                  setError(err instanceof Error ? err.message : '创建失败')
                } finally {
                  setBusy(false)
                }
              }}
            >
              <Plus size={15} /> 创建连接
            </Button>
          </section>}

          <section className="card p-5">
            <div className="flex items-center justify-between">
              <div><div className="flex items-center gap-2 section-title"><ShieldCheck size={16} className="text-indigo-500" /> 已建立的授权</div><div className="section-desc">授权状态与有效期都显示在这里。</div></div>
              <span className="badge bg-slate-100 text-slate-600">{connections.length} 个</span>
            </div>
            <div className="mt-4 space-y-2.5">
              {connections.map((connection) => (
                <div key={connection.id} className="rounded-2xl border border-slate-200 p-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2"><span className="text-[13px] font-semibold text-slate-800">{connection.name}</span><span className={`badge ${oauthStatusStyle[connection.status] || oauthStatusStyle.disconnected}`}>{oauthStatus[connection.status] || connection.status}</span></div>
                      <div className="mt-1 text-[10px] text-slate-400">{connection.scopes.join(' ') || '未设置 scope'}{connection.expires_at ? ` · 有效期至 ${new Date(connection.expires_at).toLocaleString()}` : ''}</div>
                    </div>
                    <div className="flex items-center gap-1">
                      {canWriteTools && <Button variant="secondary" className="h-8 px-2.5 text-[11px]" onClick={async () => { try { const result = await resourceApi.oauthAuthorizeUrl(connection.id); window.location.href = result.authorize_url } catch (err) { setError(err instanceof Error ? err.message : '获取授权地址失败') } }}><Globe size={13} /> {connection.status === 'connected' ? '重新授权' : '授权'}</Button>}
                      {canWriteTools && connection.status === 'connected' && <Button variant="ghost" className="h-8 px-2 text-[11px]" onClick={async () => { if (!window.confirm(`断开「${connection.name}」的授权？`)) return; await resourceApi.disconnectOAuthConnection(connection.id); await load(); setMessage('OAuth 授权已断开') }}>断开</Button>}
                      {canWriteTools && <Button variant="ghost" className="h-8 px-2 text-rose-600" onClick={async () => { if (!window.confirm(`删除 OAuth 连接「${connection.name}」？`)) return; await resourceApi.deleteOAuthConnection(connection.id); await load(); setMessage('OAuth 连接已删除') }}><Trash2 size={13} /></Button>}
                    </div>
                  </div>
                </div>
              ))}
              {!connections.length && <div className="rounded-xl bg-slate-50 px-4 py-8 text-center text-[12px] text-slate-400">还没有 OAuth 连接。</div>}
            </div>
          </section>
        </div>
      )}

      {testTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={() => setTestTarget(null)}>
          <div className="w-full max-w-2xl rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><Wrench size={20} /></span>
                <div><div className="text-[16px] font-semibold text-slate-900">测试工具「{testTarget.name}」</div><div className="mt-0.5 text-[11px] text-slate-500">直接执行一次工具调用，不会写入 Agent 对话。</div></div>
              </div>
              <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setTestTarget(null)}><X size={16} /></button>
            </div>
            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <Field label="输入 JSON" hint="根据工具 input_schema 填写参数。">
                  <textarea className="input min-h-40 font-mono text-xs" value={testInputs} onChange={(event) => setTestInputs(event.target.value)} />
                </Field>
                <Button disabled={busy} onClick={() => void runTest()}>{busy ? <><Loader2 size={14} className="animate-spin" /> 执行中…</> : <><Play size={14} /> 运行测试</>}</Button>
                {testError && <Callout tone="error">{testError}</Callout>}
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
                <div className="mb-2 text-[12px] font-semibold text-slate-600">返回结果</div>
                {testResult ? <JsonViewer value={testResult} /> : <div className="grid min-h-[180px] place-items-center text-[11px] text-slate-400">运行后在这里查看工具返回。</div>}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}