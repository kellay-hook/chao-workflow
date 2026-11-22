import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { addEdge, applyEdgeChanges, applyNodeChanges, MarkerType, type Edge, type Node } from '@xyflow/react'
import {
  ArrowLeft, Brain, Bot, CheckCircle2, Code2, Copy, ExternalLink, GitBranch, Globe, History, LayoutGrid, Loader2,
  Pencil, Play, Plus, Rocket, RotateCcw, Save, Search, Send, ShieldCheck, Sparkles, Square, Trash2, Webhook, Wrench, X,
} from 'lucide-react'
import Canvas, { type CanvasMenuEvent } from '../workflow/Canvas'
import { knowledgeApi, resourceApi, workflowApi } from '../api'
import type { AgentProfile, KnowledgeBase, ModelProfile, NodeType, Tool, WebhookEndpoint, Workflow, WorkflowDSL, WorkflowEdge, WorkflowNode, WorkflowVersion } from '../types'
import { Button, Callout, EmptyState, JsonBlock, StatusBadge } from '../components/ui'
import { useCan } from '../components/permissions'

const typeLabels: Record<string, string> = { start: '开始', end: '结束', llm: '大模型', agent: '智能体', agent_team: '多智能体', http: 'HTTP', tool: '工具', condition: '条件', approval: '审批', code: '代码', subworkflow: '子工作流', loop: '循环' }

const palette: { type: NodeType; label: string; description: string; icon: any }[] = [
  { type: 'start', label: '开始', description: '工作流入口，只能有一个', icon: Play },
  { type: 'llm', label: '大模型', description: '提示词与模型调用', icon: Brain },
  { type: 'agent', label: '智能体', description: '可调用工具的智能体', icon: Bot },
  { type: 'agent_team', label: '多智能体', description: '主管模式或自由图', icon: Sparkles },
  { type: 'http', label: 'HTTP', description: '调用外部 API', icon: Globe },
  { type: 'tool', label: '工具', description: '已注册工具或 MCP 工具', icon: Wrench },
  { type: 'condition', label: '条件', description: '根据值分支', icon: GitBranch },
  { type: 'approval', label: '审批', description: '暂停等待人工处理', icon: ShieldCheck },
  { type: 'code', label: '代码', description: '沙箱 Python', icon: Code2 },
  { type: 'subworkflow', label: '子工作流', description: '调用已发布工作流', icon: LayoutGrid },
  { type: 'loop', label: '循环', description: '遍历数据执行子流程', icon: GitBranch },
  { type: 'end', label: '结束', description: '输出工作流结果', icon: Square },
]

const paletteGroups: { label: string; types: NodeType[] }[] = [
  { label: '基础', types: ['start', 'end'] },
  { label: 'AI 能力', types: ['llm', 'agent', 'agent_team'] },
  { label: '集成与复用', types: ['http', 'tool', 'subworkflow'] },
  { label: '流程控制', types: ['condition', 'approval', 'loop', 'code'] },
]

type MenuState =
  | { kind: 'node'; id: string; x: number; y: number }
  | { kind: 'edge'; id: string; x: number; y: number }
  | { kind: 'pane'; x: number; y: number; flowX: number; flowY: number }

function defaultConfig(type: NodeType, models: ModelProfile[], tools: Tool[], agents: AgentProfile[]): Record<string, any> {
  switch (type) {
    case 'llm': return { model_profile_id: models[0]?.id ?? '', prompt: '{{ inputs.prompt }}', response_format: 'text' }
    case 'http': return { method: 'GET', url: 'https://httpbin.org/get' }
    case 'condition': return { cases: [{ id: 'yes', expr: 'inputs.ok' }] }
    case 'approval': return { title: '审批此步骤', description: '', risk_level: 'medium' }
    case 'tool': return { tool_id: tools[0]?.id ?? '', input: {} }
    case 'agent': return { agent_profile_id: agents[0]?.id ?? '', goal: '{{ inputs.goal }}' }
    case 'agent_team': return { mode: 'supervisor', supervisor_profile_id: agents[0]?.id ?? '', worker_profile_ids: agents.slice(1).map((agent) => agent.id), max_handoffs: 12, max_steps: 20, token_budget: 100000 }
    case 'code': return { language: 'python', source: 'result = {"ok": True}', input: {} }
    case 'end': return { outputs: { output: '{{ nodes }}' } }
    case 'loop': return { workflow_version_id: '', items_expr: 'inputs.items', max_iterations: 100 }
    case 'subworkflow': return { workflow_version_id: '', input: {} }
    default: return {}
  }
}

function summaryFor(node: WorkflowNode): string {
  const config = node.config || {}
  switch (node.type) {
    case 'llm': return config.model_profile_id ? `模式l ${String(config.model_profile_id).slice(0, 8)}...` : '选择模型'
    case 'http': return `${config.method || 'GET'} ${String(config.url || '').replace(/^https?:\/\//, '').slice(0, 34)}`
    case 'condition': return `${(config.cases || []).length} 个分支`
    case 'approval': return config.title || '人工审批'
    case 'tool': return config.tool_id || '选择工具'
    case 'agent': return config.agent_profile_id ? '已绑定 Agent' : '选择 Agent'
    case 'agent_team': return config.mode === 'graph' ? '自由图团队' : '主管 + 成员'
    case 'code': return `${String(config.source || '').split('\n').length} 行 Python`
    case 'loop': return config.items_expr || '遍历数据'
    case 'subworkflow': return config.workflow_version_id ? '已发布版本' : '选择版本'
    case 'end': return `${Object.keys(config.outputs || {}).length} 个输出字段`
    default: return node.type
  }
}

function toRfNodes(nodes: WorkflowNode[], selectedId: string | null): Node[] {
  return nodes.map((node) => ({
    id: node.id,
    type: 'flow',
    position: node.position ?? { x: 80, y: 80 },
    data: { label: node.name || node.id, nodeType: node.type, summary: summaryFor(node), selected: node.id === selectedId },
  }))
}

function toRfEdges(edges: WorkflowEdge[], selectedEdgeId: string | null): Edge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.source_port && edge.source_port !== 'default' ? edge.source_port : undefined,
    type: 'smoothstep',
    animated: true,
    selected: edge.id === selectedEdgeId,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: edge.id === selectedEdgeId ? '#4f46e5' : '#818cf8', strokeWidth: edge.id === selectedEdgeId ? 3 : 2 },
  }))
}

export type RunField = {
  name: string
  label: string
  type: string
  required: boolean
  default?: any
  description?: string
}

function buildRunFields(dsl: WorkflowDSL | undefined, nodes: WorkflowNode[]): RunField[] {
  const schema = dsl?.inputs || {}
  const properties = { ...((schema.properties || {}) as Record<string, any>) }
  const adjacency = new Map<string, string[]>()
  for (const edge of dsl?.edges || []) {
    const list = adjacency.get(edge.source) ?? []
    list.push(edge.target)
    adjacency.set(edge.source, list)
  }
  const start = nodes.find((node) => node.type === 'start')?.id
  const reachable = new Set<string>()
  if (start) {
    const queue = [start]
    while (queue.length) {
      const current = queue.pop() as string
      if (reachable.has(current)) continue
      reachable.add(current)
      queue.push(...(adjacency.get(current) ?? []))
    }
  } else {
    nodes.forEach((node) => reachable.add(node.id))
  }
  const source = JSON.stringify(nodes.filter((node) => reachable.has(node.id)).map((node) => node.config || {}))
  for (const match of source.matchAll(/inputs\.([A-Za-z_][A-Za-z0-9_]*)/g)) {
    const name = match[1]
    if (!properties[name]) properties[name] = { type: 'string', title: name }
  }
  const requiredNames = new Set<string>((Array.isArray(schema.required) ? schema.required : Object.keys(properties)) as string[])
  return Object.entries(properties).map(([name, value]) => ({
    name,
    label: String(value?.title || name),
    type: String(value?.type || 'string'),
    required: requiredNames.has(name),
    default: value?.default,
    description: value?.description,
  }))
}
export default function WorkflowEditorPage() {
  const canEditWorkflow = useCan('workflow.update')
  const canPublishWorkflow = useCan('workflow.publish')
  const canRunWorkflow = useCan('workflow.run')
  const { id = '' } = useParams()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [nodes, setNodes] = useState<WorkflowNode[]>([])
  const [edges, setEdges] = useState<WorkflowEdge[]>([])
  const [rfNodes, setRfNodes] = useState<Node[]>([])
  const [rfEdges, setRfEdges] = useState<Edge[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [models, set模式ls] = useState<ModelProfile[]>([])
  const [tools, setTools] = useState<Tool[]>([])
  const [agents, setAgents] = useState<AgentProfile[]>([])
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [issues, setIssues] = useState<{ code: string; message: string; node_id?: string }[]>([])
  const [toast, setToast] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [runInputs, set运行Inputs] = useState('{"prompt":"Hello, introduce yourself"}')
  const [runValues, set运行Values] = useState<Record<string, any>>({})
  const [runAdvanced, set运行Advanced] = useState(false)
  const [versions, setVersions] = useState<WorkflowVersion[]>([])
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [triggerOpen, setTriggerOpen] = useState(false)
  const [webhooks, setWebhooks] = useState<WebhookEndpoint[]>([])
  const [webhookName, setWebhookName] = useState('默认 Webhook')
  const [requireSignature, setRequireSignature] = useState(true)
  const [webhookSecret, setWebhookSecret] = useState('')
  const [webhookBusy, setWebhookBusy] = useState(false)
  const [webhookResult, setWebhookResult] = useState<{ run_id: string; status: string; payload: Record<string, any> } | null>(null)
  const [webhookError, setWebhookError] = useState('')
  const [webhookPayload, setWebhookPayload] = useState(JSON.stringify({
    event: 'demo.order.created',
    id: 'evt_demo_001',
    data: { order_id: 'A1001', amount: 299, customer: 'Demo User' },
  }, null, 2))
  const [paletteQuery, setPaletteQuery] = useState('')
  const [clipboard, setClipboard] = useState<WorkflowNode | null>(null)
  const [advanced, setAdvanced] = useState(false)

  useEffect(() => {
    void Promise.all([workflowApi.get(id), resourceApi.models(), resourceApi.tools(), resourceApi.agents(), knowledgeApi.list(), workflowApi.versions(id)])
      .then(([wf, modelData, toolData, agentData, kbData, versionData]) => {
        setWorkflow(wf); setNodes(wf.draft_dsl.nodes); setEdges(wf.draft_dsl.edges); setVersions(versionData)
        setRfNodes(toRfNodes(wf.draft_dsl.nodes, null)); setRfEdges(toRfEdges(wf.draft_dsl.edges, null))
        set模式ls(modelData); setTools(toolData); setAgents(agentData); setKbs(kbData)
        setSelectedId(wf.draft_dsl.nodes.find((node) => node.type !== 'start')?.id ?? null)
      })
      .catch((err) => setError(err.message))
  }, [id])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 3200)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    setRfNodes((current) => current.map((node) => ({ ...node, data: { ...node.data, selected: node.id === selectedId } })))
    setRfEdges(toRfEdges(edges, selectedEdgeId))
  }, [selectedId, selectedEdgeId, edges])

  const selected = useMemo(() => nodes.find((node) => node.id === selectedId) ?? null, [nodes, selectedId])
  const selectedEdge = useMemo(() => edges.find((edge) => edge.id === selectedEdgeId) ?? null, [edges, selectedEdgeId])
  const filteredPalette = palette.filter((item) => `${item.label} ${item.description} ${item.type}`.toLowerCase().includes(paletteQuery.toLowerCase()))
  const runFields = useMemo(() => buildRunFields(workflow?.draft_dsl, nodes), [workflow?.draft_dsl, nodes])

  useEffect(() => {
    if (!runOpen) return
    const initial: Record<string, any> = {}
    for (const field of runFields) initial[field.name] = field.default ?? ''
    set运行Values(initial)
    set运行Inputs(JSON.stringify(initial, null, 2))
  }, [runOpen, workflow?.id])
  const markDirty = () => setDirty(true)

  const sync = (nextNodes: WorkflowNode[], nextEdges: WorkflowEdge[], nextSelected = selectedId, nextEdge = selectedEdgeId) => {
    setNodes(nextNodes); setEdges(nextEdges); setRfNodes(toRfNodes(nextNodes, nextSelected)); setRfEdges(toRfEdges(nextEdges, nextEdge))
  }

  const addNode = (type: NodeType, position?: { x: number; y: number }) => {
    if (!workflow) return
    if (type === 'start' && nodes.some((node) => node.type === 'start')) return
    const nodeId = `${type}_${Math.random().toString(36).slice(2, 7)}`
    const node: WorkflowNode = {
      id: nodeId, type, name: `${type} ${nodes.length + 1}`,
      config: defaultConfig(type, models, tools, agents),
      position: position ?? { x: 180 + (nodes.length % 4) * 260, y: 100 + Math.floor(nodes.length / 4) * 160 },
    }
    sync([...nodes, node], edges, nodeId, null)
    setSelectedId(nodeId); setSelectedEdgeId(null); setMenu(null); markDirty()
  }

  const removeNode = (nodeId: string) => {
    sync(nodes.filter((node) => node.id !== nodeId), edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId), null, null)
    setSelectedId(null); setSelectedEdgeId(null); setMenu(null); markDirty(); setToast('节点已删除')
  }

  const duplicateNode = (nodeId: string) => {
    const source = nodes.find((node) => node.id === nodeId)
    if (!source) return
    const copy: WorkflowNode = {
      ...source, id: `${source.type}_${Math.random().toString(36).slice(2, 7)}`,
      name: `${source.name || source.type} 副本`, config: JSON.parse(JSON.stringify(source.config || {})),
      position: { x: source.position.x + 36, y: source.position.y + 36 },
    }
    sync([...nodes, copy], edges, copy.id, null)
    setSelectedId(copy.id); setMenu(null); markDirty(); setToast('节点已复制')
  }

  const removeEdge = (edgeId: string) => {
    sync(nodes, edges.filter((edge) => edge.id !== edgeId), selectedId, null)
    setSelectedEdgeId(null); setMenu(null); markDirty(); setToast('连线已删除')
  }

  const createNodeModel = (type: NodeType, position: { x: number; y: number }, name?: string): WorkflowNode => ({
    id: `${type}_${Math.random().toString(36).slice(2, 7)}`,
    type,
    name: name || `${type} ${nodes.length + 1}`,
    config: defaultConfig(type, models, tools, agents),
    position,
  })

  const copyNode = async (nodeId: string) => {
    const node = nodes.find((item) => item.id === nodeId)
    if (!node) return
    setClipboard(JSON.parse(JSON.stringify(node)))
    try { await navigator.clipboard.writeText(JSON.stringify(node, null, 2)) } catch { /* ignore */ }
    setMenu(null); setToast('节点已复制')
  }

  const pasteNode = (position?: { x: number; y: number }) => {
    if (!clipboard) return
    const copy: WorkflowNode = {
      ...clipboard,
      id: `${clipboard.type}_${Math.random().toString(36).slice(2, 7)}`,
      name: `${clipboard.name || clipboard.type} 副本`,
      config: JSON.parse(JSON.stringify(clipboard.config || {})),
      position: position ?? { x: clipboard.position.x + 40, y: clipboard.position.y + 40 },
    }
    sync([...nodes, copy], edges, copy.id, null)
    setSelectedId(copy.id); setSelectedEdgeId(null); setMenu(null); markDirty(); setToast('节点已粘贴')
  }

  const insertAfter = (nodeId: string, type: NodeType) => {
    const source = nodes.find((node) => node.id === nodeId)
    if (!source) return
    const node = createNodeModel(type, { x: source.position.x + 300, y: source.position.y + 20 })
    const edge = { id: `edge_${Math.random().toString(36).slice(2, 8)}`, source: nodeId, target: node.id, source_port: 'default', target_port: 'default' }
    sync([...nodes, node], [...edges, edge], node.id, null)
    setSelectedId(node.id); setSelectedEdgeId(null); setMenu(null); markDirty(); setToast('已添加下游节点')
  }

  const insertOnEdge = (edgeId: string, type: NodeType) => {
    const edge = edges.find((item) => item.id === edgeId)
    if (!edge) return
    const source = nodes.find((node) => node.id === edge.source)
    const target = nodes.find((node) => node.id === edge.target)
    const position = {
      x: ((source?.position.x ?? 100) + (target?.position.x ?? 400)) / 2,
      y: ((source?.position.y ?? 100) + (target?.position.y ?? 100)) / 2,
    }
    const node = createNodeModel(type, position)
    const first = { id: `edge_${Math.random().toString(36).slice(2, 8)}`, source: edge.source, target: node.id, source_port: 'default', target_port: 'default' }
    const second = { id: `edge_${Math.random().toString(36).slice(2, 8)}`, source: node.id, target: edge.target, source_port: 'default', target_port: 'default' }
    sync([...nodes, node], [...edges.filter((item) => item.id !== edgeId), first, second], node.id, null)
    setSelectedId(node.id); setSelectedEdgeId(null); setMenu(null); markDirty(); setToast('已在连线中插入节点')
  }

  const reverseEdge = (edgeId: string) => {
    const nextEdges = edges.map((edge) => edge.id === edgeId ? { ...edge, source: edge.target, target: edge.source } : edge)
    sync(nodes, nextEdges, selectedId, edgeId)
    setMenu(null); markDirty(); setToast('已反转连线方向')
  }

  const duplicateById = (nodeId: string) => {
    const source = nodes.find((node) => node.id === nodeId)
    if (!source) return
    const copy: WorkflowNode = {
      ...source, id: `${source.type}_${Math.random().toString(36).slice(2, 7)}`,
      name: `${source.name || source.type} 副本`, config: JSON.parse(JSON.stringify(source.config || {})),
      position: { x: source.position.x + 36, y: source.position.y + 36 },
    }
    sync([...nodes, copy], edges, copy.id, null)
    setSelectedId(copy.id); setMenu(null); markDirty(); setToast('节点已复制')
  }

  const renameNode = (nodeId: string) => {
    const node = nodes.find((item) => item.id === nodeId)
    if (!node) return
    const name = window.prompt('节点名称', node.name || '')
    if (name !== null && name.trim()) {
      sync(nodes.map((item) => item.id === nodeId ? { ...item, name: name.trim() } : item), edges, nodeId, selectedEdgeId)
      markDirty(); setToast('节点已重命名')
    }
    setMenu(null)
  }

  const updateSelected = (patch: Partial<WorkflowNode>) => {
    if (!selected) return
    sync(nodes.map((node) => node.id === selected.id ? { ...node, ...patch } : node), edges, selected.id, selectedEdgeId)
    markDirty()
  }

  const updateConfig = (key: string, value: any) => {
    if (!selected) return
    updateSelected({ config: { ...selected.config, [key]: value } })
  }

  const updateConfigJson = (key: string, value: string, fallback: any) => {
    try { updateConfig(key, value.trim() ? JSON.parse(value) : fallback) } catch { updateConfig(key, value) }
  }

  const updateEdgePort = (port: string) => {
    if (!selectedEdge) return
    sync(nodes, edges.map((edge) => edge.id === selectedEdge.id ? { ...edge, source_port: port } : edge), selectedId, selectedEdge.id)
    markDirty()
  }

  const updateInputSchema = (value: string) => {
    if (!workflow) return
    try {
      const parsed = JSON.parse(value)
      setWorkflow({ ...workflow, draft_dsl: { ...workflow.draft_dsl, inputs: parsed } })
      setDirty(true)
      setToast('输入 Schema 已更新')
    } catch {
      setError('输入 Schema 不是有效 JSON')
    }
  }
  const autoLayout = useCallback(() => {
    const incoming = new Map<string, number>(); nodes.forEach((node) => incoming.set(node.id, 0))
    edges.forEach((edge) => incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1))
    const level = new Map<string, number>(); const queue = nodes.filter((node) => (incoming.get(node.id) ?? 0) === 0).map((node) => node.id)
    queue.forEach((nodeId) => level.set(nodeId, 0))
    const outgoing = new Map<string, string[]>()
    edges.forEach((edge) => { const list = outgoing.get(edge.source) ?? []; list.push(edge.target); outgoing.set(edge.source, list) })
    const seen = new Set<string>()
    while (queue.length) {
      const current = queue.shift() as string
      if (seen.has(current)) continue
      seen.add(current)
      for (const next of outgoing.get(current) ?? []) {
        level.set(next, Math.max(level.get(next) ?? 0, (level.get(current) ?? 0) + 1))
        if (!seen.has(next)) queue.push(next)
      }
    }
    const counts = new Map<number, number>()
    const nextNodes = nodes.map((node) => {
      const depth = level.get(node.id) ?? 0; const row = counts.get(depth) ?? 0
      counts.set(depth, row + 1)
      return { ...node, position: { x: 80 + depth * 300, y: 90 + row * 150 } }
    })
    sync(nextNodes, edges, selectedId, selectedEdgeId); markDirty(); setToast('自动布局 applied')
  }, [nodes, edges, selectedId, selectedEdgeId])

  const save = async () => {
    if (!workflow) return null
    const positions = new Map(rfNodes.map((node) => [node.id, node.position]))
    const dsl = { ...workflow.draft_dsl, nodes: nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })), edges }
    const updated = await workflowApi.update(workflow.id, { name: workflow.name, dsl, version_no: workflow.version_no })
    setWorkflow(updated); setNodes(updated.draft_dsl.nodes); setEdges(updated.draft_dsl.edges)
    sync(updated.draft_dsl.nodes, updated.draft_dsl.edges, selectedId, selectedEdgeId); setDirty(false)
    return updated
  }

  const validate = async () => {
    if (!workflow) return
    setBusy(true); setError('')
    try {
      await save(); const result = await workflowApi.validate(workflow.id)
      setIssues(result.issues); setToast(result.valid ? '校验通过' : '发现校验问题')
    } catch (err) { setError(err instanceof Error ? err.message : '校验失败') } finally { setBusy(false) }
  }

  const loadVersions = async () => {
    if (!workflow) return
    setVersionsLoading(true)
    try {
      setVersions(await workflowApi.versions(workflow.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载版本记录失败')
    } finally {
      setVersionsLoading(false)
    }
  }

  const openVersions = async () => {
    setVersionsOpen(true)
    await loadVersions()
  }

  const publish = async () => {
    if (!workflow) return
    setBusy(true); setError('')
    try {
      await save()
      const version = await workflowApi.publish(workflow.id)
      const refreshed = await workflowApi.get(workflow.id)
      setWorkflow(refreshed)
      setVersions(await workflowApi.versions(workflow.id))
      setToast(`发布成功：v${version.version}，现在可以运行或配置触发器`)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '发布失败')
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } finally { setBusy(false) }
  }

  const run = async () => {
    if (!workflow) return
    setBusy(true); setError('')
    try {
      await save()
      const fresh = await workflowApi.get(workflow.id)
      if (!fresh.current_version_id) throw new Error('请先发布工作流再运行')
      const values = runAdvanced ? JSON.parse(runInputs || '{}') : runValues
      const missing = runFields.filter((field) => field.required && (values[field.name] === undefined || values[field.name] === '')).map((field) => field.name)
      if (missing.length) throw new Error(`缺少必填输入: ${missing.join(', ')}`)
      const runData = await workflowApi.run(workflow.id, values)
      setRunOpen(false); window.location.href = `/runs/${runData.id}`
    } catch (err) { setError(err instanceof Error ? err.message : '运行失败') } finally { setBusy(false) }
  }

  const loadWebhooks = async () => {
    if (!workflow) return []
    try {
      const items = await workflowApi.webhooks(workflow.id)
      setWebhooks(items)
      return items
    } catch (err) {
      setWebhookError(err instanceof Error ? err.message : '加载 Webhook 失败')
      return []
    }
  }

  const openTrigger = async () => {
    setTriggerOpen(true)
    setWebhookError('')
    setWebhookResult(null)
    setWebhookSecret('')
    await loadWebhooks()
  }

  const createWebhook = async () => {
    if (!workflow || !webhookName.trim()) return
    setWebhookBusy(true)
    setWebhookError('')
    try {
      const created = await workflowApi.createWebhook(workflow.id, webhookName.trim(), requireSignature)
      setWebhookSecret(created.hmac_secret || '')
      setWebhookName('')
      setToast('Webhook 已创建')
      await loadWebhooks()
    } catch (err) {
      setWebhookError(err instanceof Error ? err.message : '创建 Webhook 失败')
    } finally {
      setWebhookBusy(false)
    }
  }

  const testWebhook = async (endpoint: WebhookEndpoint) => {
    if (!workflow) return
    setWebhookBusy(true)
    setWebhookError('')
    setWebhookResult(null)
    try {
      const payload = JSON.parse(webhookPayload || '{}')
      const result = await workflowApi.testWebhook(workflow.id, endpoint.id, payload)
      setWebhookResult(result)
      setToast('测试事件已发送')
    } catch (err) {
      setWebhookError(err instanceof Error ? err.message : '发送测试事件失败')
    } finally {
      setWebhookBusy(false)
    }
  }

  const deleteWebhook = async (endpoint: WebhookEndpoint) => {
    if (!workflow || !window.confirm(`删除 Webhook「${endpoint.name}」？外部地址会立即失效。`)) return
    try {
      await workflowApi.deleteWebhook(workflow.id, endpoint.id)
      await loadWebhooks()
      setToast('Webhook 已删除')
    } catch (err) {
      setWebhookError(err instanceof Error ? err.message : '删除 Webhook 失败')
    }
  }

  const copyText = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setToast('已复制')
    } catch {
      setWebhookError('复制失败，请手动选择文本')
    }
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = document.activeElement as HTMLElement | null
      const typing = target && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)
      if (event.key === 'Escape') { setMenu(null); setRunOpen(false); setTriggerOpen(false); setVersionsOpen(false); return }
      if (typing) return
      if (!canEditWorkflow) return
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selectedId) removeNode(selectedId); else if (selectedEdgeId) removeEdge(selectedEdgeId)
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c' && selectedId) {
        event.preventDefault(); void copyNode(selectedId); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'v') {
        event.preventDefault(); pasteNode(); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd' && selectedId) {
        event.preventDefault(); duplicateById(selectedId); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault(); void save().then(() => setToast('草稿已保存')).catch((err) => setError(err.message))
      }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, selectedEdgeId, nodes, edges, workflow, clipboard, canEditWorkflow])

  if (error && !workflow) return (
    <div className="space-y-4">
      <Callout tone="error" title="无法打开工作流">{error}</Callout>
      <Link to="/workflows" className="btn-secondary">返回工作流列表</Link>
    </div>
  )
  if (!workflow) return (
    <div className="card grid min-h-[320px] place-items-center p-8">
      <div className="text-center">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
        <div className="mt-3 text-sm font-medium text-slate-600">正在加载工作流…</div>
      </div>
    </div>
  )
  return (
    <div className="space-y-4">
      <div className="card flex flex-col gap-4 p-5 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <Link to="/workflows" className="inline-flex items-center gap-1 text-[12px] font-medium text-slate-500 hover:text-slate-800"><ArrowLeft size={13} /> 返回工作流</Link>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <input disabled={!canEditWorkflow} className="w-full max-w-md border-0 bg-transparent p-0 text-[22px] font-semibold tracking-[-0.02em] text-slate-950 outline-none focus:ring-0 disabled:text-slate-500 sm:w-72" value={workflow.name} onChange={(e) => { setWorkflow({ ...workflow, name: e.target.value }); setDirty(true) }} />
            <span className="badge bg-slate-100 text-slate-600">{workflow.current_version_id ? `已发布 v${workflow.version_no}` : '草稿'}</span>
            <span className={`badge ${dirty ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}><span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />{dirty ? '有未保存修改' : '已保存'}</span>
          </div>
          <div className="mt-1 text-[11px] text-slate-400">左键拖拽与连线 · 右键节点或连线打开菜单 · Ctrl/Cmd+S 保存草稿</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canEditWorkflow && <>
            <Button variant="secondary" onClick={() => save().then(() => setToast('草稿已保存')).catch((err) => setError(err.message))}><Save size={15} /> 保存</Button>
            <Button variant="secondary" onClick={validate} disabled={busy}><CheckCircle2 size={15} /> 校验</Button>
            <Button variant="secondary" onClick={autoLayout}><LayoutGrid size={15} /> 自动布局</Button>
          </>}
          {workflow.current_version_id && canRunWorkflow && <Button variant="secondary" onClick={() => setRunOpen(true)}><Play size={15} /> 运行</Button>}
          {canPublishWorkflow && <Button onClick={publish} disabled={busy}><Rocket size={15} /> 发布版本</Button>}
        </div>
      </div>

      <div className={`flex flex-col gap-3 rounded-2xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${workflow.current_version_id ? 'border-emerald-200 bg-emerald-50/70' : 'border-amber-200 bg-amber-50/70'}`}>
        <div className="flex items-start gap-2.5">
          <span className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl ${workflow.current_version_id ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
            {workflow.current_version_id ? <CheckCircle2 size={16} /> : <Rocket size={16} />}
          </span>
          <div>
            <div className={`text-[13px] font-semibold ${workflow.current_version_id ? 'text-emerald-900' : 'text-amber-900'}`}>
              {workflow.current_version_id ? `已发布 v${workflow.version_no} · 可运行` : '当前是草稿 · 尚未发布'}
            </div>
            <div className={`mt-0.5 text-[11px] ${workflow.current_version_id ? 'text-emerald-700/80' : 'text-amber-700/80'}`}>
              {workflow.current_version_id
                ? (versions[0] ? `最近发布于 ${new Date(versions[0].published_at).toLocaleString()}，可运行或配置定时 / Webhook 触发器` : '已生成可运行版本，可运行或配置触发器')
                : '发布后才会生成可运行版本和外部触发入口'}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {workflow.current_version_id && canRunWorkflow && (
            <Button className="h-9 px-3 text-[12px]" onClick={() => setRunOpen(true)}><Play size={14} /> 运行此版本</Button>
          )}
          {!workflow.current_version_id && canPublishWorkflow && (
            <Button className="h-9 px-3 text-[12px]" onClick={() => void publish()} disabled={busy}><Rocket size={14} /> 立即发布</Button>
          )}
          <Button variant="secondary" className="h-9 px-3 text-[12px]" onClick={() => void openVersions()}><History size={14} /> 版本记录</Button>
          {canEditWorkflow && <Button variant="secondary" className="h-9 px-3 text-[12px]" onClick={() => void openTrigger()}><Webhook size={14} /> 触发器</Button>}
        </div>
      </div>

      {!canEditWorkflow && <Callout tone="info" title="只读模式">当前角色可以查看画布和版本，但不能修改、发布或配置触发器。</Callout>}
      {error && <Callout tone="error">{error}</Callout>}
      {toast && <div className="fixed right-6 top-20 z-50 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl">{toast}</div>}
      {issues.length > 0 && (
        <Callout tone="warning" title="发布前需要处理">
          {issues.map((issue) => <div key={`${issue.code}-${issue.node_id ?? ''}`}>[{issue.code}] {issue.node_id ? `${issue.node_id}: ` : ''}{issue.message}</div>)}
        </Callout>
      )}
      <div className={`grid gap-4 ${canEditWorkflow ? 'xl:grid-cols-[240px_minmax(0,1fr)_340px]' : 'xl:grid-cols-[minmax(0,1fr)_340px]'}`}>
        {canEditWorkflow && <div className="card flex h-[520px] flex-col overflow-hidden p-3 xl:h-[calc(100vh-250px)] xl:min-h-[620px]">
          <div className="relative mb-3 shrink-0">
            <Search size={14} className="absolute left-3 top-3 text-slate-400" />
            <input className="input pl-9" placeholder="搜索节点" value={paletteQuery} onChange={(e) => setPaletteQuery(e.target.value)} />
          </div>
          <div className="flex-1 space-y-4 overflow-auto pr-1">
            {paletteGroups.map((group) => {
              const items = filteredPalette.filter((item) => group.types.includes(item.type))
              if (!items.length) return null
              return (
                <div key={group.label}>
                  <div className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{group.label}</div>
                  <div className="space-y-1">
                    {items.map((item) => {
                      const Icon = item.icon
                      const disabled = item.type === 'start' && nodes.some((node) => node.type === 'start')
                      return (
                        <button
                          key={item.type}
                          disabled={disabled}
                          className="group flex w-full items-center gap-2.5 rounded-xl border border-transparent px-2.5 py-2 text-left transition hover:border-indigo-100 hover:bg-indigo-50/50 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-transparent disabled:hover:bg-transparent"
                          onClick={() => addNode(item.type)}
                        >
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600 transition group-hover:bg-white group-hover:text-indigo-600 group-hover:shadow-sm"><Icon size={15} /></span>
                          <span className="min-w-0 flex-1"><span className="block text-[12px] font-semibold text-slate-700">{item.label}</span><span className="block truncate text-[10px] text-slate-400">{disabled ? '已存在开始节点' : item.description}</span></span>
                          <Plus size={13} className="text-slate-300 transition group-hover:text-indigo-500" />
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="mt-3 shrink-0 border-t border-slate-100 pt-3 text-[10px] leading-relaxed text-slate-400">
            右键画布添加节点，右键节点或连线打开菜单；Delete 删除选中项，Ctrl/Cmd+S 保存。
          </div>
        </div>}
        <div className="card relative h-[520px] overflow-hidden xl:h-[calc(100vh-250px)] xl:min-h-[620px]">
          <Canvas
            readOnly={!canEditWorkflow}
            nodes={rfNodes}
            edges={rfEdges}
            onNodesChange={(changes: any) => setRfNodes((current) => applyNodeChanges(changes, current))}
            onEdgesChange={(changes: any) => {
              setRfEdges((current) => {
                const next = applyEdgeChanges(changes, current)
                setEdges((previous) => previous.filter((edge) => next.some((item) => item.id === edge.id)))
                return next
              })
              markDirty()
            }}
            onConnect={(connection: any) => {
              const edgeId = `edge_${Math.random().toString(36).slice(2, 8)}`
              const nextEdges = [...edges, { id: edgeId, source: connection.source, target: connection.target, source_port: 'default', target_port: 'default' }]
              sync(nodes, nextEdges, selectedId, edgeId); setSelectedEdgeId(edgeId); markDirty()
            }}
            onNodeClick={(nodeId) => { setSelectedId(nodeId); setSelectedEdgeId(null); setMenu(null) }}
            onNodeDoubleClick={(nodeId) => { setSelectedId(nodeId); setAdvanced(true) }}
            onEdgeClick={(edgeId) => { setSelectedEdgeId(edgeId); setSelectedId(null); setMenu(null) }}
            onNodeDragStop={(nodeId, position) => {
              setRfNodes((current) => current.map((node) => node.id === nodeId ? { ...node, position } : node))
              setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, position } : node)); markDirty()
            }}
            onPaneClick={() => { setMenu(null); setSelectedId(null); setSelectedEdgeId(null) }}
            onNodeContextMenu={(event: CanvasMenuEvent) => { if (event.id) setSelectedId(event.id); setMenu({ kind: 'node', id: event.id as string, x: event.x, y: event.y }) }}
            onEdgeContextMenu={(event: CanvasMenuEvent) => { if (event.id) setSelectedEdgeId(event.id); setMenu({ kind: 'edge', id: event.id as string, x: event.x, y: event.y }) }}
            onPaneContextMenu={(event: CanvasMenuEvent) => setMenu({ kind: 'pane', x: event.x, y: event.y, flowX: event.flowX ?? 120, flowY: event.flowY ?? 120 })}
          />
        </div>
        <fieldset disabled={!canEditWorkflow} className="card h-[520px] min-w-0 overflow-auto p-4 xl:h-[calc(100vh-250px)] xl:min-h-[620px]">
          {selectedEdge ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between"><div className="font-semibold">连线</div><Button variant="danger" onClick={() => removeEdge(selectedEdge.id)}><Trash2 size={16} /> 删除</Button></div>
              <div className="rounded-xl bg-slate-50 p-3 text-sm text-slate-600"><div>从： <span className="font-mono text-xs">{selectedEdge.source}</span></div><div>到： <span className="font-mono text-xs">{selectedEdge.target}</span></div></div>
              <div><div className="label">源端口</div><input className="input" value={selectedEdge.source_port ?? 'default'} onChange={(e) => updateEdgePort(e.target.value)} /><p className="mt-1 text-xs text-slate-500">条件节点使用 case id 作为源端口。</p></div>
            </div>
          ) : selected ? (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div><div className="font-semibold">节点设置</div><div className="mt-1 flex items-center gap-2"><span className="badge bg-indigo-50 text-indigo-700">{typeLabels[selected.type] || selected.type}</span><span className="font-mono text-[11px] text-slate-400">{selected.id}</span></div></div>
                <div className="flex gap-1"><Button variant="secondary" onClick={() => duplicateNode(selected.id)}><Copy size={15} /></Button><Button variant="danger" onClick={() => removeNode(selected.id)}><Trash2 size={15} /></Button></div>
              </div>
              <div><div className="label">显示名称</div><input className="input" value={selected.name ?? ''} onChange={(e) => updateSelected({ name: e.target.value })} /></div>
              {selected.type === 'start' && (
                <div className="space-y-2 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-indigo-700">工作流输入 Schema</div>
                  <textarea className="input min-h-32 font-mono text-xs" defaultValue={JSON.stringify(workflow.draft_dsl.inputs ?? {}, null, 2)} onBlur={(event) => updateInputSchema(event.target.value)} />
                  <div className="text-xs text-indigo-700">识别字段: {runFields.map((field) => field.name).join(', ') || 'none'}</div>
                  <div className="text-[11px] text-indigo-500">Use JSON Schema properties and required fields. Templates like {'{{ inputs.question }}'} are detected automatically.</div>
                </div>
              )}
              {selected.type === 'llm' && (<>
                <div><div className="label">模型配置</div><select className="input" value={selected.config.model_profile_id ?? ''} onChange={(e) => updateConfig('model_profile_id', e.target.value)}><option value="">默认模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} - {model.model}</option>)}</select></div>
                <div><div className="label">提示词模板</div><textarea className="input min-h-28 font-mono text-xs" value={selected.config.prompt ?? ''} onChange={(e) => updateConfig('prompt', e.target.value)} /></div>
                <div><div className="label">输出格式</div><select className="input" value={selected.config.response_format ?? 'text'} onChange={(e) => updateConfig('response_format', e.target.value)}><option value="text">text</option><option value="json">json</option></select></div>
              </>)}
              {selected.type === 'http' && (<>
                <div><div className="label">方法</div><select className="input" value={selected.config.method ?? 'GET'} onChange={(e) => updateConfig('method', e.target.value)}>{['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((method) => <option key={method}>{method}</option>)}</select></div>
                <div><div className="label">URL</div><input className="input" value={selected.config.url ?? ''} onChange={(e) => updateConfig('url', e.target.value)} /></div>
                <div><div className="label">请求体 JSON</div><textarea className="input min-h-24 font-mono text-xs" defaultValue={JSON.stringify(selected.config.body ?? {}, null, 2)} onBlur={(e) => updateConfigJson('body', e.target.value, {})} /></div>
              </>)}
              {selected.type === 'condition' && <div><div className="label">条件 JSON</div><textarea className="input min-h-36 font-mono text-xs" defaultValue={JSON.stringify(selected.config.cases ?? [], null, 2)} onBlur={(e) => updateConfigJson('cases', e.target.value, [])} /></div>}
              {selected.type === 'approval' && (<>
                <div><div className="label">标题</div><input className="input" value={selected.config.title ?? ''} onChange={(e) => updateConfig('title', e.target.value)} /></div>
                <div><div className="label">描述</div><textarea className="input min-h-20" value={selected.config.description ?? ''} onChange={(e) => updateConfig('description', e.target.value)} /></div>
              </>)}
              {selected.type === 'tool' && (<>
                <div><div className="label">工具</div><select className="input" value={selected.config.tool_id ?? ''} onChange={(e) => updateConfig('tool_id', e.target.value)}><option value="knowledge_search">knowledge_search</option>{tools.map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}</select></div>
                <div><div className="label">知识库 ID</div><input className="input" placeholder="Comma separated" value={(selected.config.kb_ids ?? []).join(',')} onChange={(e) => updateConfig('kb_ids', e.target.value.split(',').map((value: string) => value.trim()).filter(Boolean))} /></div>
                <div><div className="label">输入 JSON</div><textarea className="input min-h-24 font-mono text-xs" defaultValue={JSON.stringify(selected.config.input ?? {}, null, 2)} onBlur={(e) => updateConfigJson('input', e.target.value, {})} /></div>
              </>)}
              {selected.type === 'agent' && (<>
                <div><div className="label">Agent 配置</div><select className="input" value={selected.config.agent_profile_id ?? ''} onChange={(e) => updateConfig('agent_profile_id', e.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></div>
                <div><div className="label">目标模板</div><textarea className="input min-h-24" value={selected.config.goal ?? ''} onChange={(e) => updateConfig('goal', e.target.value)} /></div>
              </>)}
              {selected.type === 'agent_team' && (<>
                <div><div className="label">模式</div><select className="input" value={selected.config.mode ?? 'supervisor'} onChange={(e) => updateConfig('mode', e.target.value)}><option value="supervisor">主管 + 成员</option><option value="graph">自由图</option></select></div>
                <div><div className="label">主管 / 入口 Agent</div><select className="input" value={selected.config.supervisor_profile_id ?? ''} onChange={(e) => updateConfig('supervisor_profile_id', e.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></div>
                <div><div className="label">成员配置 ID</div><input className="input" value={(selected.config.worker_profile_ids ?? []).join(',')} onChange={(e) => updateConfig('worker_profile_ids', e.target.value.split(',').map((value: string) => value.trim()).filter(Boolean))} /></div>
                <div><div className="label">图 Agent JSON</div><textarea className="input min-h-28 font-mono text-xs" defaultValue={JSON.stringify(selected.config.agents ?? [], null, 2)} onBlur={(e) => updateConfigJson('agents', e.target.value, [])} /></div>
                <div><div className="label">交接 JSON</div><textarea className="input min-h-28 font-mono text-xs" defaultValue={JSON.stringify(selected.config.handoffs ?? [], null, 2)} onBlur={(e) => updateConfigJson('handoffs', e.target.value, [])} /></div>
              </>)}
              {selected.type === 'code' && <div><div className="label">Python 代码</div><textarea className="input min-h-56 font-mono text-xs" value={selected.config.source ?? ''} onChange={(e) => updateConfig('source', e.target.value)} /></div>}
              {selected.type === 'end' && <div><div className="label">输出映射 JSON</div><textarea className="input min-h-32 font-mono text-xs" defaultValue={JSON.stringify(selected.config.outputs ?? {}, null, 2)} onBlur={(e) => updateConfigJson('outputs', e.target.value, {})} /></div>}
              {selected.type === 'subworkflow' && <div><div className="label">工作流版本 ID</div><input className="input" value={selected.config.workflow_version_id ?? ''} onChange={(e) => updateConfig('workflow_version_id', e.target.value)} /></div>}
              {selected.type === 'loop' && (<>
                <div><div className="label">迭代表达式</div><input className="input" placeholder="inputs.items" value={selected.config.items_expr ?? ''} onChange={(e) => updateConfig('items_expr', e.target.value)} /></div>
                <div><div className="label">工作流版本 ID</div><input className="input" value={selected.config.workflow_version_id ?? ''} onChange={(e) => updateConfig('workflow_version_id', e.target.value)} /></div>
                <div><div className="label">最大迭代次数</div><input className="input" type="number" value={selected.config.max_iterations ?? 100} onChange={(e) => updateConfig('max_iterations', Number(e.target.value))} /></div>
              </>)}
              <div className="border-t border-slate-100 pt-3"><button className="text-xs font-medium text-indigo-600" onClick={() => setAdvanced(!advanced)}>{advanced ? '隐藏' : '显示'}高级 JSON</button>{advanced && <div className="mt-2"><JsonBlock value={selected} /></div>}</div>
            </div>
          ) : <EmptyState title="选择节点或连线" hint="点击节点编辑，或右键画布添加节点。" />}
        </fieldset>
      </div>
      {menu && (<>
        <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} onContextMenu={(event) => { event.preventDefault(); setMenu(null) }} />
        <div className="fixed z-50 max-h-[72vh] w-64 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-2xl" style={{ left: Math.min(menu.x, window.innerWidth - 276), top: Math.min(menu.y, window.innerHeight - 460) }}>
          {menu.kind === 'pane' ? (<>
            <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">添加节点</div>
            {palette.filter((item) => item.type !== 'start' && item.type !== 'end').map((item) => {
              const Icon = item.icon
              return <button key={item.type} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => addNode(item.type, { x: menu.flowX, y: menu.flowY })}><Icon size={14} className="text-slate-400" /> {item.label}</button>
            })}
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => addNode('end', { x: menu.flowX, y: menu.flowY })}><Square size={14} className="text-slate-400" /> 结束</button>
            <div className="my-1 border-t border-slate-100" />
            {clipboard && <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => pasteNode({ x: menu.flowX, y: menu.flowY })}><Copy size={14} className="text-slate-400" /> 粘贴节点</button>}
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => { setMenu(null); autoLayout() }}><LayoutGrid size={14} className="text-slate-400" /> 自动布局</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => { setMenu(null); setRunOpen(true) }}><Play size={14} className="text-slate-400" /> 运行工作流</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => { setMenu(null); setSelectedId(null); setSelectedEdgeId(null) }}><X size={14} className="text-slate-400" /> 清空选择</button>
          </>) : menu.kind === 'node' ? (<>
            <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">节点操作</div>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => { setSelectedId(menu.id); setMenu(null) }}><Brain size={14} className="text-slate-400" /> 编辑配置</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => renameNode(menu.id)}><Pencil size={14} className="text-slate-400" /> 重命名</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => duplicateById(menu.id)}><Copy size={14} className="text-slate-400" /> 复制节点</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => void copyNode(menu.id)}><Copy size={14} className="text-slate-400" /> 复制 JSON</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={async () => { try { await navigator.clipboard.writeText(menu.id); setToast('节点 ID 已复制') } catch {} setMenu(null) }}><Copy size={14} className="text-slate-400" /> 复制节点 ID</button>
            <div className="my-1 border-t border-slate-100" />
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">添加下游节点</div>
            <div className="grid grid-cols-2 gap-1">
              {(['llm','agent','http','tool','approval','code'] as NodeType[]).map((type) => {
                const item = palette.find((entry) => entry.type === type)
                if (!item) return null
                const Icon = item.icon
                return <button key={type} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-slate-50" onClick={() => insertAfter(menu.id, type)}><Icon size={13} className="text-slate-400" /> {item.label}</button>
              })}
            </div>
            <div className="my-1 border-t border-slate-100" />
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-rose-600 hover:bg-rose-50" onClick={() => removeNode(menu.id)}><Trash2 size={14} /> 删除节点</button>
          </>) : (<>
            <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">连线操作</div>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => { setSelectedEdgeId(menu.id); setMenu(null) }}><GitBranch size={14} className="text-slate-400" /> 编辑端口</button>
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50" onClick={() => reverseEdge(menu.id)}><RotateCcw size={14} className="text-slate-400" /> 反转方向</button>
            <div className="my-1 border-t border-slate-100" />
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">在连线中插入节点</div>
            <div className="grid grid-cols-2 gap-1">
              {(['llm','agent','http','tool','approval','code'] as NodeType[]).map((type) => {
                const item = palette.find((entry) => entry.type === type)
                if (!item) return null
                const Icon = item.icon
                return <button key={type} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-slate-50" onClick={() => insertOnEdge(menu.id, type)}><Icon size={13} className="text-slate-400" /> {item.label}</button>
              })}
            </div>
            <div className="my-1 border-t border-slate-100" />
            <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-rose-600 hover:bg-rose-50" onClick={() => removeEdge(menu.id)}><Trash2 size={14} /> 删除连线</button>
          </>)}
        </div>
      </>)}
      {runOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" onClick={() => setRunOpen(false)}>
          <div className="w-full max-w-xl rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div><div className="text-[16px] font-semibold text-slate-900">运行工作流</div><div className="mt-1 text-[11px] leading-relaxed text-slate-500">运行会使用当前已发布版本，输入字段根据节点模板自动推断。</div></div>
              <button className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" onClick={() => setRunOpen(false)}><X size={16} /></button>
            </div>
            {!runAdvanced && runFields.length > 0 ? (
              <div className="mt-4 max-h-[52vh] space-y-3 overflow-auto pr-1">
                {runFields.map((field) => (
                  <div key={field.name}>
                    <label className="label flex items-center gap-1">{field.label}{field.required && <span className="text-rose-500">*</span>}</label>
                    {field.type === 'boolean' ? (
                      <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={Boolean(runValues[field.name])} onChange={(event) => set运行Values({ ...runValues, [field.name]: event.target.checked })} /> 启用</label>
                    ) : field.type === 'number' ? (
                      <input className="input" type="number" value={runValues[field.name] ?? ''} onChange={(event) => set运行Values({ ...runValues, [field.name]: Number(event.target.value) })} />
                    ) : field.type === 'object' || field.type === 'array' ? (
                      <textarea className="input min-h-24 font-mono text-xs" defaultValue={JSON.stringify(runValues[field.name] ?? (field.type === 'array' ? [] : {}), null, 2)} onBlur={(event) => { try { set运行Values({ ...runValues, [field.name]: JSON.parse(event.target.value) }) } catch { setError(`${field.label} 必须是有效 JSON`) } }} />
                    ) : (
                      <textarea className="input min-h-20" value={runValues[field.name] ?? ''} onChange={(event) => set运行Values({ ...runValues, [field.name]: event.target.value })} placeholder={field.description || `输入${field.label}`} />
                    )}
                    {field.description && <p className="mt-1 text-xs text-slate-500">{field.description}</p>}
                  </div>
                ))}
              </div>
            ) : (
              <textarea className="input mt-4 min-h-40 font-mono text-xs" value={runInputs} onChange={(event) => set运行Inputs(event.target.value)} />
            )}
            <div className="mt-3 flex items-center justify-between">
              <button className="text-xs font-medium text-indigo-600" onClick={() => {
                if (!runAdvanced) set运行Inputs(JSON.stringify(runValues, null, 2))
                else { try { set运行Values(JSON.parse(runInputs || '{}')) } catch { setError('高级 JSON 格式无效') } }
                set运行Advanced(!runAdvanced)
              }}>{runAdvanced ? '使用表单输入' : '高级 JSON'}</button>
              <span className="text-xs text-slate-400">{runFields.length} 个输入字段</span>
            </div>
            <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={() => setRunOpen(false)}>取消</Button><Button onClick={run} disabled={busy}><Play size={16} /> 开始运行</Button></div>
          </div>
        </div>
      )}

      {versionsOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={() => setVersionsOpen(false)}>
          <div className="max-h-[88vh] w-full max-w-2xl overflow-auto rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><History size={21} /></span>
                <div><div className="text-[17px] font-semibold text-slate-900">版本记录</div><div className="mt-0.5 text-[11px] text-slate-500">每次发布都会生成一个不可变版本，运行会绑定当前版本。</div></div>
              </div>
              <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setVersionsOpen(false)}><X size={16} /></button>
            </div>
            <div className="mt-5 space-y-3">
              {versionsLoading && <div className="grid place-items-center py-10"><Loader2 size={22} className="animate-spin text-indigo-500" /></div>}
              {!versionsLoading && versions.map((version) => {
                const current = workflow.current_version_id === version.id
                return (
                  <div key={version.id} className={`rounded-2xl border p-4 ${current ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200'}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-semibold text-slate-900">v{version.version}</span>
                        {current && <span className="badge bg-emerald-100 text-emerald-700">当前运行版本</span>}
                        <span className="text-[10px] text-slate-400">{new Date(version.published_at).toLocaleString()}</span>
                      </div>
                      <span className="text-[10px] text-slate-400">{(version.dsl?.nodes || []).length} 节点 · {version.dsl_hash.slice(0, 10)}…</span>
                    </div>
                    <details className="mt-3 rounded-xl bg-slate-50">
                      <summary className="cursor-pointer list-none px-3 py-2 text-[10px] font-semibold text-slate-500">查看该版本 DSL</summary>
                      <div className="border-t border-slate-200 p-2"><JsonBlock value={version.dsl} /></div>
                    </details>
                  </div>
                )
              })}
              {!versionsLoading && !versions.length && <div className="rounded-xl bg-slate-50 px-4 py-10 text-center text-[12px] text-slate-400">还没有发布版本。点击「发布版本」生成第一个可运行版本。</div>}
            </div>
            <div className="mt-5 flex justify-end"><Button variant="secondary" onClick={() => setVersionsOpen(false)}>关闭</Button></div>
          </div>
        </div>
      )}

      {triggerOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={() => setTriggerOpen(false)}>
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><Webhook size={21} /></span>
                <div>
                  <div className="text-[17px] font-semibold text-slate-900">触发方式 · Webhook</div>
                  <div className="mt-0.5 text-[11px] leading-relaxed text-slate-500">外部系统向 Webhook URL 发送 JSON，即可触发这条工作流。</div>
                </div>
              </div>
              <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setTriggerOpen(false)}><X size={16} /></button>
            </div>

            {!workflow.current_version_id && (
              <div className="mt-4"><Callout tone="warning" title="请先发布工作流">Webhook 只能触发已发布版本。</Callout></div>
            )}

            <div className="mt-5 space-y-5">
              <section>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="section-title">已创建的 Webhook</div>
                    <div className="section-desc">每个地址对应一条独立入口，可随时删除。</div>
                  </div>
                  <span className="badge bg-slate-100 text-slate-600">{webhooks.length} 个</span>
                </div>
                <div className="mt-3 space-y-2.5">
                  {webhooks.map((endpoint) => (
                    <div key={endpoint.id} className="rounded-2xl border border-slate-200 p-3.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[12px] font-semibold text-slate-800">{endpoint.name}</span>
                          <span className={`badge ${endpoint.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{endpoint.enabled ? '已启用' : '已禁用'}</span>
                          <span className={`badge ${endpoint.require_signature ? 'bg-amber-50 text-amber-700' : 'bg-sky-50 text-sky-700'}`}>{endpoint.require_signature ? '需要 HMAC 签名' : '无需签名'}</span>
                        </div>
                        <div className="flex gap-1">
                          <Button variant="ghost" className="h-8 px-2 text-[11px]" onClick={() => void copyText(endpoint.url)}><Copy size={12} /> 复制</Button>
                          <Button variant="secondary" className="h-8 px-2.5 text-[11px]" disabled={webhookBusy || !workflow.current_version_id} onClick={() => void testWebhook(endpoint)}><Send size={12} /> 测试</Button>
                          <Button variant="ghost" className="h-8 px-2 text-rose-600" onClick={() => void deleteWebhook(endpoint)}><Trash2 size={13} /></Button>
                        </div>
                      </div>
                      <code className="mt-2 block break-all rounded-xl bg-slate-950 px-3 py-2 font-mono text-[10px] leading-relaxed text-slate-200">{endpoint.url}</code>
                    </div>
                  ))}
                  {!webhooks.length && <div className="rounded-xl bg-slate-50 px-4 py-6 text-center text-[12px] text-slate-400">还没有 Webhook。创建后即可复制地址给外部系统。</div>}
                </div>
              </section>

              <section className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-slate-800"><Plus size={14} className="text-indigo-500" /> 新建 Webhook</div>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input className="input flex-1" placeholder="Webhook 名称，例如：订单事件" value={webhookName} onChange={(event) => setWebhookName(event.target.value)} />
                  <Button className="h-10 shrink-0" disabled={webhookBusy || !webhookName.trim()} onClick={() => void createWebhook()}>
                    {webhookBusy ? <><Loader2 size={14} className="animate-spin" /> 创建中…</> : <><Plus size={14} /> 创建</>}
                  </Button>
                </div>
                <label className="mt-2 flex items-center gap-2 text-[11px] text-slate-600">
                  <input type="checkbox" checked={requireSignature} onChange={(event) => setRequireSignature(event.target.checked)} /> 要求 HMAC 签名（推荐；取消后外部系统可直接 POST JSON）
                </label>
              </section>

              {webhookSecret && (
                <Callout tone="warning" title="签名密钥只显示一次，请立即保存">
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <code className="break-all rounded-lg bg-white px-2 py-1 font-mono text-[11px] text-slate-700 ring-1 ring-amber-200">{webhookSecret}</code>
                    <Button variant="secondary" className="h-7 px-2 text-[10px]" onClick={() => void copyText(webhookSecret)}><Copy size={11} /> 复制密钥</Button>
                  </div>
                </Callout>
              )}

              <section>
                <div className="section-title">发送测试事件</div>
                <div className="section-desc">测试按钮会直接创建一次运行，不需要手工计算签名。</div>
                <textarea className="input mt-2 min-h-32 font-mono text-xs" value={webhookPayload} onChange={(event) => setWebhookPayload(event.target.value)} />
              </section>

              {webhookError && <Callout tone="error">{webhookError}</Callout>}
              {webhookResult && (
                <Callout tone="success" title="测试事件已触发">
                  <div className="mt-1 flex flex-wrap items-center gap-3">
                    <Link className="inline-flex items-center gap-1 font-semibold text-emerald-800 underline" to={`/runs/${webhookResult.run_id}`}>查看运行 {webhookResult.run_id.slice(0, 10)}… <ExternalLink size={12} /></Link>
                    <StatusBadge status={webhookResult.status} />
                  </div>
                  <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-white/70 p-2 text-[10px] text-slate-600 ring-1 ring-emerald-100">{JSON.stringify(webhookResult.payload, null, 2)}</pre>
                </Callout>
              )}

              <section className="rounded-2xl bg-slate-50 p-4 text-[11px] leading-relaxed text-slate-500">
                <div className="font-semibold text-slate-700">外部系统如何调用</div>
                <div className="mt-1">向 Webhook URL POST JSON。若开启签名，需要添加请求头 <code className="rounded bg-white px-1 py-0.5 font-mono text-[10px] ring-1 ring-slate-200">x-webhook-signature: sha256=&lt;HMAC_SHA256(secret, raw_body)&gt;</code>。响应会返回 <code className="rounded bg-white px-1 py-0.5 font-mono text-[10px] ring-1 ring-slate-200">run_id</code>。</div>
                <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-3 font-mono text-[10px] text-slate-200">{`curl -X POST "${webhooks[0]?.url || 'https://你的域名/api/v1/hooks/wh_xxx'}" \\
  -H "Content-Type: application/json" \\
${webhooks[0]?.require_signature ? '  -H "x-webhook-signature: sha256=<hmac>" \\\n' : ''}  -d '{"event":"demo.order.created","data":{"order_id":"A1001"}}'`}</pre>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
