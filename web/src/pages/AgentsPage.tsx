import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Bot, BookOpen, CheckCircle2, Database, MessageSquare, Pencil, Play, Plus, Puzzle, RotateCcw, Search, SlidersHorizontal, Sparkles, Trash2, Wrench } from 'lucide-react'
import { knowledgeApi, resourceApi } from '../api'
import type { AgentProfile, AgentSessionSummary, AgentTestResponse, KnowledgeBase, ModelProfile, Tool } from '../types'
import { Button, Callout, EmptyState, GuideSteps, PageHeader, StatusBadge } from '../components/ui'
import { useCan } from '../components/permissions'
import JsonViewer from '../components/JsonViewer'

type Tab = 'config' | 'debug'
const emptyForm = { name: '', role_prompt: '你是一个谨慎、可靠的智能助手。必要时使用工具，并在使用知识库时保留引用。', model_profile_id: '', tool_ids: [] as string[], kb_ids: [] as string[], max_iterations: 8, temperature: 0.2, output_schema: '' }

export default function AgentsPage() {
  const canWriteAgent = useCan('agent.write')
  const canRunAgent = useCan('agent.run')
  const [agents, setAgents] = useState<AgentProfile[]>([])
  const [models, setModels] = useState<ModelProfile[]>([])
  const [tools, setTools] = useState<Tool[]>([])
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [tab, setTab] = useState<Tab>('config')
  const [form, setForm] = useState(emptyForm)
  const [query, setQuery] = useState('')
  const [goal, setGoal] = useState('请介绍你自己，并说明你能做什么。')
  const [inputsJson, setInputsJson] = useState('{}')
  const [result, setResult] = useState<AgentTestResponse | null>(null)
  const [history, setHistory] = useState<Record<string, any>[]>([])
  const [sessions, setSessions] = useState<AgentSessionSummary[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const selected = useMemo(() => agents.find((agent) => agent.id === selectedId) ?? null, [agents, selectedId])
  const filteredAgents = useMemo(() => { const keyword = query.trim().toLowerCase(); return keyword ? agents.filter((agent) => `${agent.name} ${agent.role_prompt}`.toLowerCase().includes(keyword)) : agents }, [agents, query])
  const modelName = (id: string | null) => models.find((model) => model.id === id)?.name ?? '默认模型'

  const load = async () => {
    const [agentData, modelData, toolData, kbData] = await Promise.all([resourceApi.agents(), resourceApi.models(), resourceApi.tools(), knowledgeApi.list()])
    setAgents(agentData); setModels(modelData); setTools(toolData); setKbs(kbData)
    if (!selectedId && agentData[0]) selectAgent(agentData[0])
  }
  useEffect(() => { void load().catch((err) => setError(err.message)) }, [])

  const loadSessionDetail = async (id: string) => {
    try {
      const item = await resourceApi.agentSession(id)
      setSessionId(item.id)
      setHistory(item.messages || [])
      setResult(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载会话失败')
    }
  }

  const loadSessions = async (agentId: string, preferredId?: string | null) => {
    try {
      const items = await resourceApi.agentSessions(agentId)
      setSessions(items)
      const current = [preferredId ?? sessionId, items[0]?.id].find(
        (id) => Boolean(id) && items.some((item) => item.id === id),
      ) ?? null
      setSessionId(current)
      if (current) await loadSessionDetail(current)
      else setHistory([])
    } catch {
      setSessions([])
    }
  }

  const selectAgent = (agent: AgentProfile) => {
    setSelectedId(agent.id); setIsNew(false); setTab('config'); setResult(null); setHistory([]); setSessionId(null); void loadSessions(agent.id)
    setForm({ name: agent.name, role_prompt: agent.role_prompt, model_profile_id: agent.model_profile_id ?? '', tool_ids: [...(agent.tool_ids || [])], kb_ids: [...(agent.kb_ids || [])], max_iterations: agent.max_iterations, temperature: agent.temperature, output_schema: agent.output_schema && Object.keys(agent.output_schema).length ? JSON.stringify(agent.output_schema, null, 2) : '' })
  }
  const startNew = () => { setSelectedId(null); setIsNew(true); setTab('config'); setForm(emptyForm); setResult(null); setHistory([]); setSessionId(null); setSessions([]) }
  const toggleId = (key: 'tool_ids' | 'kb_ids', id: string) => setForm((current) => ({ ...current, [key]: current[key].includes(id) ? current[key].filter((item) => item !== id) : [...current[key], id] }))

  const saveAgent = async () => {
    if (!form.name.trim()) return
    setBusy(true); setError(''); setMessage('')
    try {
      let outputSchema: Record<string, any> = {}
      if (form.output_schema.trim()) outputSchema = JSON.parse(form.output_schema)
      const payload = { name: form.name.trim(), role_prompt: form.role_prompt, model_profile_id: form.model_profile_id || null, tool_ids: form.tool_ids, kb_ids: form.kb_ids, max_iterations: form.max_iterations, temperature: form.temperature, output_schema: outputSchema }
      if (selectedId) { await resourceApi.updateAgent(selectedId, payload); setMessage('Agent 已更新') }
      else { const created = await resourceApi.createAgent(payload); setSelectedId(created.id); setIsNew(false); setMessage('Agent 已创建') }
      const latest = await resourceApi.agents(); setAgents(latest)
      const current = latest.find((agent) => agent.id === (selectedId || latest[0]?.id))
      if (current) selectAgent(current)
    } catch (err) { setError(err instanceof Error ? err.message : '保存失败') } finally { setBusy(false) }
  }
  const deleteAgent = async (agent: AgentProfile) => {
    if (!window.confirm(`确定删除 Agent「${agent.name}」吗？`)) return
    try {
      await resourceApi.deleteAgent(agent.id)
      const latest = await resourceApi.agents(); setAgents(latest)
      if (selectedId === agent.id) { if (latest[0]) selectAgent(latest[0]); else startNew() }
      setMessage('Agent 已删除')
    } catch (err) { setError(err instanceof Error ? err.message : '删除失败') }
  }
  const runTest = async () => {
    if (!selectedId) { setError('请先保存 Agent'); return }
    setTesting(true); setError(''); setResult(null)
    try {
      const inputs = JSON.parse(inputsJson || '{}')
      let sid = sessionId
      if (!sid) {
        const created = await resourceApi.createAgentSession(selectedId, goal.slice(0, 80))
        sid = created.id
        setSessionId(sid)
      }
      const res = await resourceApi.sendAgentSessionMessage(sid, goal, inputs)
      setResult(res)
      setHistory(res.messages || [])
      await loadSessions(selectedId, sid)
      setResult(res)
    } catch (err) { setError(err instanceof Error ? err.message : '调试运行失败') } finally { setTesting(false) }
  }
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Agents"
        title="Agent 智能体"
        description="定义角色提示词，绑定模型、工具和知识库，在调试面板验证多轮对话与工具调用。"
        icon={Bot}
        actions={<><Link to="/plugins" className="btn-secondary"><Puzzle size={15} /> 插件市场</Link>{canWriteAgent && <Button onClick={startNew}><Plus size={15} /> 新建 Agent</Button>}</>}
      />
      <GuideSteps
        steps={[
          { title: '配置角色', description: '写清职责、边界和输出格式，必要时补充 JSON Schema。' },
          { title: '绑定能力', description: '勾选可用工具与知识库，工具风险越高越需要审批。' },
          { title: '调试多轮', description: '在调试页连续提问，确认上下文和工具调用符合预期。' },
          { title: '持续迭代', description: '根据对话轨迹调整提示词、模型或工具配置后保存。' },
        ]}
      />
      {!canWriteAgent && <Callout tone="info" title="只读模式">当前角色可以查看 Agent 配置和调试历史，但不能修改配置。</Callout>}
      {error && <Callout tone="error">{error}</Callout>}
      {message && <Callout tone="success">{message}</Callout>}
      <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="card h-fit p-4">
          <div className="mb-3 flex items-center justify-between px-0.5">
            <div>
              <div className="section-title">Agent 列表</div>
              <div className="section-desc">共 {agents.length} 个</div>
            </div>
          </div>
          <div className="relative mb-3"><Search size={14} className="absolute left-3 top-3 text-slate-400" /><input className="input pl-9" placeholder="搜索 Agent" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <div className="space-y-1.5">{filteredAgents.map((agent) => (
            <div key={agent.id} className={`group rounded-xl px-3 py-2.5 transition ${selectedId === agent.id ? 'bg-indigo-50 ring-1 ring-indigo-100' : 'hover:bg-slate-50'}`}>
              <button className="flex w-full items-center gap-2 text-left" onClick={() => selectAgent(agent)}><span className={`grid h-9 w-9 place-items-center rounded-xl font-semibold ${selectedId === agent.id ? 'bg-indigo-100' : 'bg-slate-100 text-slate-600'}`}>{agent.name.slice(0, 1).toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{agent.name}</span><span className="block truncate text-[11px] text-slate-400">{modelName(agent.model_profile_id)} · {agent.tool_ids.length} 工具 · {agent.kb_ids.length} 知识库</span></span></button>
              {canWriteAgent && <div className="mt-1 flex justify-end opacity-0 transition group-hover:opacity-100"><button className="rounded-lg p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600" onClick={() => void deleteAgent(agent)}><Trash2 size={13} /></button></div>}
            </div>
          ))}{!filteredAgents.length && <div className="px-3 py-8 text-center text-sm text-slate-400">暂无 Agent</div>}</div>
          <div className="mt-4 rounded-xl bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-500">Agent 可以绑定多个工具和知识库。知识库工具属于低风险只读操作，写工具会在工作流运行中进入审批。</div>
        </aside>
        <section className="min-w-0 space-y-4">
          {(selected || isNew) ? (<>
            <div className="card flex flex-wrap items-start justify-between gap-3 p-5">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-200/70"><Bot size={21} /></span>
                <div>
                  <h2 className="text-[17px] font-semibold tracking-[-0.01em]">{isNew ? '新建 Agent' : form.name || '未命名 Agent'}</h2>
                  <p className="mt-1 text-[12px] text-slate-500">{isNew ? '配置角色、模型和可用资源' : `${modelName(form.model_profile_id)} · ${form.tool_ids.length} 工具 · ${form.kb_ids.length} 知识库`}</p>
                </div>
              </div>
              <div className="flex gap-2">{canWriteAgent && <>{!isNew && <Button variant="danger" onClick={() => selected && void deleteAgent(selected)}><Trash2 size={15} /> 删除</Button>}<Button onClick={() => void saveAgent()} disabled={busy || !form.name.trim()}>{busy ? '保存中...' : isNew ? '创建 Agent' : '保存配置'}</Button></>}</div>
            </div>
            <div className="flex gap-1 border-b border-slate-200">{[{ id: 'config', label: '配置' },{ id: 'debug', label: '调试' }].map((item) => (<button key={item.id} onClick={() => setTab(item.id as Tab)} className={`tab-btn ${tab === item.id ? 'tab-btn-active' : ''}`}>{item.label}</button>))}</div>
            {tab === 'config' && (
              <fieldset disabled={!canWriteAgent} className="grid min-w-0 gap-4 min-[1360px]:grid-cols-[minmax(0,1fr)_320px]">
                <div className="space-y-4"><div className="card space-y-3 p-5">
                  <div className="flex items-center gap-2 font-semibold"><SlidersHorizontal size={16} /> 基础配置</div>
                  <div><div className="label">名称</div><input className="input" placeholder="例如：售后助手" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></div>
                  <div><div className="label">角色提示词</div><textarea className="input min-h-40" value={form.role_prompt} onChange={(event) => setForm({ ...form, role_prompt: event.target.value })} /></div>
                  <div className="grid gap-3 md:grid-cols-2"><div><div className="label">模型</div><select className="input" value={form.model_profile_id} onChange={(event) => setForm({ ...form, model_profile_id: event.target.value })}><option value="">使用默认模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} - {model.model}</option>)}</select></div><div><div className="label">最大迭代次数</div><input className="input" type="number" min={1} max={30} value={form.max_iterations} onChange={(event) => setForm({ ...form, max_iterations: Number(event.target.value) })} /></div></div>
                  <div><div className="label">温度</div><input className="input" type="number" min={0} max={2} step={0.1} value={form.temperature} onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })} /></div>
                  <div><div className="label">输出 JSON Schema（可选）</div><textarea className="input min-h-28 font-mono text-xs" placeholder='{"type":"object","properties":{"answer":{"type":"string"}}}' value={form.output_schema} onChange={(event) => setForm({ ...form, output_schema: event.target.value })} /></div>
                </div></div>
                <div className="space-y-4">
                  <div className="card p-5"><div className="mb-3 flex items-center gap-2 font-semibold"><Wrench size={16} /> 可用工具</div><div className="space-y-2">{tools.map((tool) => (<label key={tool.id} className="flex cursor-pointer items-start gap-2 rounded-xl border border-slate-100 p-2.5 hover:bg-slate-50"><input type="checkbox" className="mt-1" checked={form.tool_ids.includes(tool.id)} onChange={() => toggleId('tool_ids', tool.id)} /><span className="min-w-0"><span className="block text-sm font-medium">{tool.name}</span><span className="block truncate text-[11px] text-slate-500">{tool.description || tool.type} · {tool.risk_level}</span></span></label>))}{!tools.length && <div className="text-sm text-slate-400">暂无工具，请先在「工具 / MCP」中创建。</div>}</div></div>
                  <div className="card p-5"><div className="mb-3 flex items-center gap-2 font-semibold"><Database size={16} /> 绑定知识库</div><div className="space-y-2">{kbs.map((kb) => (<label key={kb.id} className="flex cursor-pointer items-start gap-2 rounded-xl border border-slate-100 p-2.5 hover:bg-slate-50"><input type="checkbox" className="mt-1" checked={form.kb_ids.includes(kb.id)} onChange={() => toggleId('kb_ids', kb.id)} /><span className="min-w-0"><span className="block text-sm font-medium">{kb.name}</span><span className="block truncate text-[11px] text-slate-500">{kb.chunk_size} tokens / {kb.chunk_overlap} overlap</span></span></label>))}{!kbs.length && <div className="text-sm text-slate-400">暂无知识库。</div>}</div></div>
                </div>
              </fieldset>
            )}
            {tab === 'debug' && (
              <div className="grid gap-4 min-[1360px]:grid-cols-[minmax(0,1fr)_380px]">
                <div className="space-y-4">
                  <div className="card space-y-3 p-5"><div className="flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><MessageSquare size={16} /> 调试输入</div><div className="flex items-center gap-2"><select className="h-9 w-52 rounded-xl border border-slate-200 bg-white px-3 text-[11px] font-medium text-slate-600 shadow-sm outline-none focus:border-indigo-400" value={sessionId ?? ''} onChange={(event) => { const id = event.target.value || null; if (id) void loadSessionDetail(id); else { setSessionId(null); setHistory([]); setResult(null) } }}><option value="">新对话</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}</select><Button variant="ghost" onClick={() => { setResult(null); setHistory([]); setSessionId(null); setError('') }}><RotateCcw size={14} /> 新对话</Button>{sessionId && <Button variant="ghost" onClick={async () => { const current = sessions.find((item) => item.id === sessionId); const title = window.prompt('重命名会话', current?.title || ''); if (!title?.trim()) return; try { await resourceApi.renameAgentSession(sessionId, title.trim()); if (selectedId) await loadSessions(selectedId, sessionId); setMessage('会话已重命名') } catch (err) { setError(err instanceof Error ? err.message : '重命名失败') } }}><Pencil size={14} /></Button>}{sessionId && <Button variant="ghost" className="text-rose-600" onClick={async () => { if (!window.confirm('删除当前会话及其全部消息？')) return; await resourceApi.deleteAgentSession(sessionId); setSessionId(null); setHistory([]); setResult(null); if (selectedId) await loadSessions(selectedId) }}><Trash2 size={14} /></Button>}</div></div><div><div className="label">目标 / 问题</div><textarea className="input min-h-32" value={goal} onChange={(event) => setGoal(event.target.value)} /></div><div><div className="label">额外输入 JSON（可选）</div><textarea className="input min-h-24 font-mono text-xs" value={inputsJson} onChange={(event) => setInputsJson(event.target.value)} /></div><div className="flex justify-between"><span className="text-xs text-slate-500">调试不会写入运行记录，适合验证提示词和工具配置。</span><Button onClick={() => void runTest()} disabled={testing || !selectedId || !canRunAgent}><Play size={16} /> {testing ? '运行中...' : canRunAgent ? '运行调试' : '无运行权限'}</Button></div></div>
                  {result && <div className="card p-5"><div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><Sparkles size={16} /> 输出</div><span className="text-xs text-slate-500">{result.tokens} tokens</span></div>{result.requires_approval ? (<div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"><div className="flex items-center gap-2 font-semibold"><AlertTriangle size={16} /> 需要人工审批</div><div className="mt-1">工具 {result.approval?.tool_name} 属于 {result.approval?.risk_level} 风险，调试模式不会自动执行。</div><div className="mt-2"><JsonViewer value={result.approval} /></div></div>) : <JsonViewer value={result.output ?? result.content} empty="Agent 没有返回内容" />}</div>}
                </div>
                <div className="card p-5"><div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><BookOpen size={16} /> 对话轨迹</div><span className="text-xs text-slate-400">{history.length} 条消息</span></div><div className="max-h-[620px] space-y-2 overflow-auto">{(history.length ? history : result?.messages || []).filter((message) => ['system', 'assistant', 'tool', 'user'].includes(String(message.role))).slice(-16).map((message, index) => (<div key={index} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-xs"><div className="mb-1 flex items-center justify-between"><span className="badge bg-white text-slate-600">{{ system: '系统', user: '用户', assistant: '助手', tool: '工具' }[String(message.role)] || String(message.role)}</span><span className="text-slate-400">{message.name || ''}</span></div><div className="whitespace-pre-wrap break-words text-slate-700">{String(message.content || '').slice(0, 2000)}</div></div>))}{!history.length && !result?.messages?.length && <div className="py-10 text-center text-sm text-slate-400">运行调试后可查看完整对话轨迹。</div>}</div></div>
              </div>
            )}
          </>) : <EmptyState title="选择或创建一个 Agent" hint="配置提示词、模型、工具和知识库，然后在调试面板直接测试。" />}
        </section>
      </div>
    </div>
  )
}
