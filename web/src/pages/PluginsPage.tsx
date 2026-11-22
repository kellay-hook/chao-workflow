import { useEffect, useMemo, useState } from 'react'
import {
  Binary,
  Blocks,
  Braces,
  Calculator,
  CheckCircle2,
  Clock3,
  FileText,
  Globe2,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  ScanText,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { pluginApi } from '../api'
import type { InstalledPlugin, PluginDefinition } from '../types'
import { Button, Callout, EmptyState, Field, GuideSteps, PageHeader } from '../components/ui'
import { useCan } from '../components/permissions'
import JsonViewer from '../components/JsonViewer'

const iconMap: Record<string, LucideIcon> = {
  calculator: Calculator,
  clock: Clock3,
  'file-text': FileText,
  braces: Braces,
  'scan-text': ScanText,
  binary: Binary,
  search: Search,
  globe: Globe2,
  send: Send,
}

const riskLabels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
const riskStyles: Record<string, string> = {
  low: 'bg-sky-50 text-sky-700',
  medium: 'bg-amber-50 text-amber-700',
  high: 'bg-rose-50 text-rose-700',
}

function PluginIcon({ name, size = 20, className = '' }: { name: string; size?: number; className?: string }) {
  const Icon = iconMap[name] || Blocks
  return <Icon size={size} className={className} />
}

export default function PluginsPage() {
  const canInstallPlugin = useCan('plugin.install')
  const canUninstallPlugin = useCan('plugin.uninstall')
  const canTestPlugin = useCan('plugin.test')
  const [catalog, setCatalog] = useState<PluginDefinition[]>([])
  const [installed, setInstalled] = useState<InstalledPlugin[]>([])
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('全部')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [configTarget, setConfigTarget] = useState<PluginDefinition | null>(null)
  const [configDraft, setConfigDraft] = useState<Record<string, any>>({})
  const [testTarget, setTestTarget] = useState<InstalledPlugin | null>(null)
  const [testForm, setTestForm] = useState<Record<string, any>>({})
  const [testResult, setTestResult] = useState<any>(null)
  const [testError, setTestError] = useState('')

  const load = async () => {
    const [catalogData, installedData] = await Promise.all([pluginApi.catalog(), pluginApi.installed()])
    setCatalog(catalogData)
    setInstalled(installedData)
  }

  useEffect(() => {
    void load().catch((err) => setError(err.message))
  }, [])

  const installedMap = useMemo(() => new Map(installed.map((item) => [item.id, item])), [installed])
  const categories = useMemo(() => ['全部', ...Array.from(new Set(catalog.map((item) => item.category)))], [catalog])
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return catalog.filter((item) => {
      const matchCategory = category === '全部' || item.category === category
      const matchKeyword = !keyword || `${item.name} ${item.description} ${item.vendor} ${item.category}`.toLowerCase().includes(keyword)
      return matchCategory && matchKeyword
    })
  }, [catalog, category, query])

  const openConfig = (plugin: PluginDefinition) => {
    const current = installedMap.get(plugin.id)
    const draft: Record<string, any> = {}
    for (const field of plugin.config_schema) {
      draft[field.key] = current?.config?.[field.key] ?? field.default ?? ''
    }
    setConfigTarget(plugin)
    setConfigDraft(draft)
    setError('')
    setMessage('')
  }

  const saveConfig = async () => {
    if (!configTarget) return
    setBusy(true)
    setError('')
    try {
      const current = installedMap.get(configTarget.id)
      if (current) {
        await pluginApi.update(configTarget.id, configDraft)
        setMessage(`「${configTarget.name}」配置已更新`)
      } else {
        await pluginApi.install(configTarget.id, configDraft)
        setMessage(`「${configTarget.name}」已安装，并自动生成了可绑定到 Agent 的工具`)
      }
      setConfigTarget(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存插件配置失败')
    } finally {
      setBusy(false)
    }
  }

  const uninstall = async (plugin: InstalledPlugin) => {
    if (!window.confirm(`卸载「${plugin.name}」？关联的 Agent 工具也会被删除。`)) return
    setError('')
    try {
      await pluginApi.remove(plugin.id)
      setMessage(`「${plugin.name}」已卸载`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '卸载失败')
    }
  }

  const openTest = (plugin: InstalledPlugin) => {
    const properties = (plugin.input_schema?.properties || {}) as Record<string, any>
    const draft: Record<string, any> = {}
    for (const [key, schema] of Object.entries(properties)) {
      draft[key] = schema?.default ?? (schema?.type === 'boolean' ? false : '')
    }
    setTestTarget(plugin)
    setTestForm(draft)
    setTestResult(null)
    setTestError('')
  }

  const runTest = async () => {
    if (!testTarget) return
    setBusy(true)
    setTestError('')
    setTestResult(null)
    try {
      const properties = (testTarget.input_schema?.properties || {}) as Record<string, any>
      const inputs: Record<string, any> = {}
      for (const [key, value] of Object.entries(testForm)) {
        const type = properties[key]?.type
        if (type === 'object' || type === 'array') {
          inputs[key] = typeof value === 'string' ? JSON.parse(value || (type === 'array' ? '[]' : '{}')) : value
        } else if (type === 'integer' || type === 'number') {
          inputs[key] = value === '' ? undefined : Number(value)
        } else {
          inputs[key] = value
        }
      }
      const response = await pluginApi.test(testTarget.id, inputs)
      setTestResult(response.result)
    } catch (err) {
      setTestError(err instanceof Error ? err.message : '测试失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Plugin Marketplace"
        title="插件"
        description="像安装应用一样扩展 Agent 能力。安装后会自动生成工具，可直接绑定给 Agent 或工作流节点。"
        icon={Blocks}
        actions={<Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /> 刷新</Button>}
      />

      <GuideSteps
        steps={[
          { title: '浏览插件市场', description: '按搜索、数据、集成、通讯等分类找到需要的能力。' },
          { title: '配置并安装', description: '需要外部地址的插件先填写配置；安装后自动生成工具。' },
          { title: '先测试再使用', description: '在插件详情里输入参数，确认返回结果符合预期。' },
          { title: '绑定 Agent', description: '到 Agent 配置中勾选插件工具，即可在对话中调用。' },
        ]}
      />

      {error && <Callout tone="error">{error}</Callout>}
      {message && <Callout tone="success">{message}</Callout>}
      {!canInstallPlugin && <Callout tone="info" title="只读模式">当前角色可以浏览插件市场，但不能安装、配置或卸载插件。</Callout>}

      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="section-title">已安装插件</div>
            <div className="section-desc">已安装 {installed.length} 个，每个插件都会自动生成一个同名工具。</div>
          </div>
          <span className="badge bg-indigo-50 text-indigo-700"><CheckCircle2 size={12} /> {installed.length} 个可用</span>
        </div>
        {installed.length ? (
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {installed.map((plugin) => (
              <div key={plugin.id} className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4">
                <div className="flex items-start gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-indigo-600 shadow-sm ring-1 ring-slate-200">
                    <PluginIcon name={plugin.icon} size={19} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-semibold text-slate-900">{plugin.name}</span>
                      <span className="badge bg-emerald-50 text-emerald-700">已安装</span>
                    </div>
                    <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{plugin.description}</div>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
                  <span className="badge bg-white text-slate-600 ring-1 ring-slate-200">{plugin.category}</span>
                  <span className={`badge ${riskStyles[plugin.risk_level] || riskStyles.medium}`}>{riskLabels[plugin.risk_level] || plugin.risk_level}</span>
                  <span>工具 {plugin.tool_id?.slice(0, 8) || '-'}</span>
                </div>
                <div className="mt-3 flex gap-1.5">
                  {canTestPlugin && <Button variant="secondary" className="h-8 flex-1 px-2 text-[11px]" onClick={() => openTest(plugin)}><Play size={12} /> 测试</Button>}
                  {canInstallPlugin && <Button variant="secondary" className="h-8 flex-1 px-2 text-[11px]" onClick={() => openConfig(plugin)}><Wrench size={12} /> 配置</Button>}
                  {canUninstallPlugin && <Button variant="ghost" className="h-8 px-2 text-rose-600" onClick={() => void uninstall(plugin)}><Trash2 size={13} /></Button>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4">
            <EmptyState title="还没有安装插件" hint="从下方插件市场选择第一个能力，安装后即可绑定到 Agent。" icon={Blocks} />
          </div>
        )}
      </section>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="section-title">插件市场</div>
          <div className="section-desc">共 {catalog.length} 个插件，按分类筛选或搜索名称。</div>
        </div>
        <div className="relative w-full lg:w-80">
          <Search size={14} className="absolute left-3 top-3 text-slate-400" />
          <input className="input pl-9" placeholder="搜索插件、厂商或能力" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {categories.map((item) => (
          <button
            key={item}
            onClick={() => setCategory(item)}
            className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition ${category === item ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-200' : 'border border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:text-indigo-600'}`}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((plugin) => {
          const isInstalled = installedMap.has(plugin.id)
          return (
            <div key={plugin.id} className="card card-hover flex flex-col p-5">
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-indigo-50 to-violet-50 text-indigo-600 ring-1 ring-indigo-100">
                  <PluginIcon name={plugin.icon} size={21} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[14px] font-semibold text-slate-900">{plugin.name}</span>
                    {isInstalled && <span className="badge bg-emerald-50 text-emerald-700">已安装</span>}
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-400">{plugin.vendor} · v{plugin.version}</div>
                </div>
                <span className="badge bg-slate-100 text-slate-600">{plugin.category}</span>
              </div>

              <p className="mt-3 line-clamp-2 min-h-[34px] text-[11px] leading-relaxed text-slate-500">{plugin.description}</p>

              <div className="mt-3 space-y-1.5">
                {plugin.highlights.slice(0, 2).map((item) => (
                  <div key={item} className="flex items-start gap-1.5 text-[10px] text-slate-500">
                    <CheckCircle2 size={11} className="mt-0.5 shrink-0 text-emerald-500" /> {item}
                  </div>
                ))}
              </div>

              <div className="mt-3 flex flex-wrap gap-1">
                {plugin.permissions.map((permission) => (
                  <span key={permission} className="badge bg-slate-50 text-slate-500 ring-1 ring-slate-200">{permission}</span>
                ))}
                <span className={`badge ${riskStyles[plugin.risk_level] || riskStyles.medium}`}>{riskLabels[plugin.risk_level] || plugin.risk_level}</span>
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                <span className="inline-flex items-center gap-1 text-[10px] text-slate-400"><ShieldCheck size={12} /> 安装后自动生成工具</span>
                {isInstalled ? (
                  canInstallPlugin ? <Button variant="secondary" className="h-8 px-3 text-[11px]" onClick={() => openConfig(plugin)}><Wrench size={12} /> 配置</Button> : <span className="badge bg-slate-100 text-slate-500">已安装</span>
                ) : (
                  canInstallPlugin ? <Button className="h-8 px-3 text-[11px]" onClick={() => openConfig(plugin)}>
                    {plugin.config_schema.length ? <><Plus size={12} /> 配置安装</> : <><Plus size={12} /> 安装</>}
                  </Button> : <span className="badge bg-slate-100 text-slate-500">无安装权限</span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {!filtered.length && <EmptyState title="没有匹配的插件" hint="换一个关键词或分类试试。" icon={Search} />}

      {configTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={() => setConfigTarget(null)}>
          <div className="w-full max-w-lg rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><PluginIcon name={configTarget.icon} size={21} /></span>
                <div>
                  <div className="text-[16px] font-semibold text-slate-900">{installedMap.has(configTarget.id) ? '配置' : '安装'}「{configTarget.name}」</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">{configTarget.description}</div>
                </div>
              </div>
              <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setConfigTarget(null)}><X size={16} /></button>
            </div>

            <div className="mt-5 space-y-3">
              {configTarget.config_schema.map((field) => (
                <Field key={field.key} label={`${field.label}${field.required ? ' *' : ''}`} hint={field.hint}>
                  {field.type === 'select' ? (
                    <select className="input" value={configDraft[field.key] ?? field.default ?? ''} onChange={(event) => setConfigDraft({ ...configDraft, [field.key]: event.target.value })}>
                      {(field.options || []).map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                  ) : (
                    <input
                      className="input"
                      type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
                      placeholder={field.placeholder}
                      value={configDraft[field.key] ?? ''}
                      onChange={(event) => setConfigDraft({ ...configDraft, [field.key]: event.target.value })}
                    />
                  )}
                </Field>
              ))}
              {!configTarget.config_schema.length && (
                <div className="rounded-2xl bg-slate-50 px-4 py-6 text-center text-[12px] text-slate-500">
                  这个插件无需额外配置，安装后会立即生成工具。
                </div>
              )}
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfigTarget(null)}>取消</Button>
              <Button disabled={busy} onClick={() => void saveConfig()}>
                {busy ? <><Loader2 size={14} className="animate-spin" /> 保存中…</> : installedMap.has(configTarget.id) ? '保存配置' : '安装插件'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {testTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={() => setTestTarget(null)}>
          <div className="w-full max-w-2xl rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><PluginIcon name={testTarget.icon} size={21} /></span>
                <div>
                  <div className="text-[16px] font-semibold text-slate-900">测试「{testTarget.name}」</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">不会写入 Agent 对话，只验证插件执行结果。</div>
                </div>
              </div>
              <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setTestTarget(null)}><X size={16} /></button>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                {Object.entries((testTarget.input_schema?.properties || {}) as Record<string, any>).map(([key, schema]) => {
                  const required = (testTarget.input_schema?.required || []).includes(key)
                  const label = `${schema?.description || key}${required ? ' *' : ''}`
                  if (schema?.enum) {
                    return (
                      <Field key={key} label={label}>
                        <select className="input" value={testForm[key] ?? schema.default ?? ''} onChange={(event) => setTestForm({ ...testForm, [key]: event.target.value })}>
                          {schema.enum.map((option: string) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </Field>
                    )
                  }
                  if (schema?.type === 'boolean') {
                    return <label key={key} className="flex items-center gap-2 text-[13px] text-slate-600"><input type="checkbox" checked={Boolean(testForm[key])} onChange={(event) => setTestForm({ ...testForm, [key]: event.target.checked })} /> {label}</label>
                  }
                  if (schema?.type === 'object' || schema?.type === 'array') {
                    return (
                      <Field key={key} label={label}>
                        <textarea className="input min-h-24 font-mono text-xs" value={testForm[key] ?? ''} onChange={(event) => setTestForm({ ...testForm, [key]: event.target.value })} placeholder={schema?.type === 'array' ? '[]' : '{}'} />
                      </Field>
                    )
                  }
                  return (
                    <Field key={key} label={label}>
                      <input
                        className="input"
                        type={schema?.type === 'integer' || schema?.type === 'number' ? 'number' : 'text'}
                        value={testForm[key] ?? ''}
                        onChange={(event) => setTestForm({ ...testForm, [key]: event.target.value })}
                        placeholder={schema?.type === 'string' ? '输入测试值' : ''}
                      />
                    </Field>
                  )
                })}
                <Button disabled={busy} onClick={() => void runTest()}>
                  {busy ? <><Loader2 size={14} className="animate-spin" /> 执行中…</> : <><Play size={14} /> 运行测试</>}
                </Button>
                {testError && <Callout tone="error">{testError}</Callout>}
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
                <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-slate-600"><Sparkles size={14} className="text-indigo-500" /> 返回结果</div>
                {testResult ? <JsonViewer value={testResult} /> : <div className="grid min-h-[180px] place-items-center text-[11px] text-slate-400">运行后在这里查看插件返回。</div>}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}