import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  Copy,
  FileJson,
  Globe2,
  LayoutTemplate,
  Loader2,
  PenLine,
  Search,
  ShieldCheck,
  Sparkles,
  Webhook,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { workflowApi } from '../api'
import type { Workflow, WorkflowTemplate } from '../types'
import { Button, Callout, EmptyState, Field, GuideSteps, PageHeader } from '../components/ui'
import { useCan } from '../components/permissions'

type Method = 'blank' | 'template' | 'import' | 'clone'

const typeLabels: Record<string, string> = {
  start: '开始', end: '结束', llm: '大模型', agent: '智能体', agent_team: '多智能体', http: 'HTTP',
  tool: '工具', condition: '条件', approval: '审批', code: '代码', subworkflow: '子工作流', loop: '循环',
}

const sampleDsl = {
  schema_version: '1.0',
  inputs: { type: 'object', properties: { text: { type: 'string', title: '文本', default: '你好 FlowMind' } }, required: ['text'] },
  nodes: [
    { id: 'start', type: 'start', name: '开始', config: {}, position: { x: 80, y: 160 } },
    { id: 'end', type: 'end', name: '结束', config: { outputs: { received: '{{ inputs.text }}' } }, position: { x: 460, y: 160 } },
  ],
  edges: [{ id: 'e1', source: 'start', target: 'end', source_port: 'default', target_port: 'default' }],
  settings: { timeout_sec: 1800, max_parallel: 4, on_error: 'fail' },
}

const templateIcons = { webhook: Webhook, globe: Globe2, sparkles: Sparkles, shield: ShieldCheck, clock: Clock }

export default function WorkflowCreatePage() {
  const canCreateWorkflow = useCan('workflow.create')
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const initialMethod = (params.get('mode') as Method) || 'template'
  const [method, setMethod] = useState<Method>(['blank', 'template', 'import', 'clone'].includes(initialMethod) ? initialMethod : 'template')
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [templateId, setTemplateId] = useState('')
  const [cloneId, setCloneId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('全部')
  const [importJson, setImportJson] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    void Promise.all([workflowApi.templates(), workflowApi.list()])
      .then(([templateData, workflowData]) => {
        setTemplates(templateData)
        setWorkflows(workflowData)
        if (templateData[0]) selectTemplate(templateData[0])
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const categories = useMemo(() => ['全部', ...Array.from(new Set(templates.map((item) => item.category)))], [templates])
  const filteredTemplates = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return templates.filter((item) => {
      const matchCategory = category === '全部' || item.category === category
      const matchKeyword = !keyword || `${item.name} ${item.description} ${item.category}`.toLowerCase().includes(keyword)
      return matchCategory && matchKeyword
    })
  }, [templates, search, category])

  const selectedTemplate = templates.find((item) => item.id === templateId) || null
  const selectedClone = workflows.find((item) => item.id === cloneId) || null
  const importParsed = useMemo(() => {
    if (method !== 'import' || !importJson.trim()) return { dsl: null as any, error: '', nodes: [] as { type: string; name: string }[] }
    try {
      const dsl = JSON.parse(importJson)
      const nodes = Array.isArray(dsl?.nodes) ? dsl.nodes.map((node: any) => ({ type: String(node.type || ''), name: String(node.name || node.type || '') })) : []
      if (!nodes.length) return { dsl, error: 'DSL 中至少需要一个节点', nodes }
      return { dsl, error: '', nodes }
    } catch (err) {
      return { dsl: null, error: err instanceof Error ? err.message : 'JSON 格式无效', nodes: [] as { type: string; name: string }[] }
    }
  }, [method, importJson])

  const previewNodes = useMemo<{ type: string; name: string }[]>(() => {
    if (method === 'template') return selectedTemplate?.preview_nodes || []
    if (method === 'clone') {
      return ((selectedClone?.draft_dsl?.nodes || []) as any[]).map((node) => ({ type: String(node.type || ''), name: String(node.name || node.type || '') }))
    }
    if (method === 'import') return importParsed.nodes
    return [{ type: 'start', name: '开始' }, { type: 'end', name: '结束' }]
  }, [method, selectedTemplate, selectedClone, importParsed])

  function selectTemplate(template: WorkflowTemplate) {
    setTemplateId(template.id)
    setName(template.name)
    setDescription(template.description)
  }

  function selectClone(workflow: Workflow) {
    setCloneId(workflow.id)
    setName(`${workflow.name} 副本`)
    setDescription(workflow.description)
  }

  function chooseMethod(next: Method) {
    const nameFromTemplate = selectedTemplate && name === selectedTemplate.name
    const nameFromClone = selectedClone && name === `${selectedClone.name} 副本`
    if ((next === 'blank' || next === 'import') && (nameFromTemplate || nameFromClone)) {
      setName('')
      setDescription('')
    }
    setMethod(next)
  }

  const canCreate = Boolean(name.trim()) && !creating && !(method === 'template' && !templateId) && !(method === 'clone' && !cloneId) && !(method === 'import' && (!importParsed.dsl || importParsed.error))

  const create = async () => {
    if (!canCreate) return
    setCreating(true)
    setError('')
    try {
      let workflow: Workflow
      if (method === 'template') {
        workflow = await workflowApi.createFromTemplate(templateId, { name: name.trim(), description })
      } else if (method === 'clone' && selectedClone) {
        workflow = await workflowApi.create({ name: name.trim(), description, dsl: selectedClone.draft_dsl })
      } else if (method === 'import') {
        workflow = await workflowApi.create({ name: name.trim(), description, dsl: importParsed.dsl })
      } else {
        workflow = await workflowApi.create({ name: name.trim(), description })
      }
      navigate(`/workflows/${workflow.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建工作流失败')
    } finally {
      setCreating(false)
    }
  }

  const methods = [
    { id: 'template' as Method, title: '从模板创建', desc: '选一个可运行示例，再改成自己的流程', icon: LayoutTemplate, tone: 'from-indigo-500 to-violet-500' },
    { id: 'blank' as Method, title: '空白画布', desc: '从开始和结束节点开始自由编排', icon: PenLine, tone: 'from-sky-500 to-cyan-500' },
    { id: 'import' as Method, title: '导入 DSL', desc: '粘贴 JSON DSL，快速迁移已有流程', icon: FileJson, tone: 'from-emerald-500 to-teal-500' },
    { id: 'clone' as Method, title: '复制已有', desc: '基于现有工作流快速创建副本', icon: Copy, tone: 'from-amber-500 to-orange-500' },
  ]

  const sourceLabel = method === 'template' ? selectedTemplate?.name || '模板' : method === 'clone' ? selectedClone?.name || '已有工作流' : method === 'import' ? '导入 DSL' : '空白画布'

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Create Workflow"
        title="创建新的工作流"
        description="选择最适合你的起点：模板、空白画布、导入 DSL 或复制已有流程。创建前即可预览节点路径和输入。"
        icon={Sparkles}
        actions={<Link to="/workflows" className="btn-secondary"><ArrowLeft size={15} /> 返回列表</Link>}
      />

      <GuideSteps
        steps={[
          { title: '选择起点', description: '模板最快，空白最自由，导入适合迁移，复制适合复用。' },
          { title: '确认与命名', description: '在右侧预览节点路径，修改名称和说明。' },
          { title: '进入画布', description: '创建后直接打开画布，继续调整节点配置。' },
          { title: '校验并发布', description: '校验通过后发布版本，再运行或配置触发器。' },
        ]}
      />

      {!canCreateWorkflow && <Callout tone="info" title="当前角色没有创建工作流权限">你可以浏览模板和节点预览，但只有编辑者、管理员或所有者可以创建工作流。</Callout>}
      {error && <Callout tone="error">{error}</Callout>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {methods.map((item) => {
              const Icon = item.icon
              const active = method === item.id
              return (
                <button
                  key={item.id}
                  onClick={() => chooseMethod(item.id)}
                  className={`card card-hover p-4 text-left transition ${active ? 'border-indigo-300 ring-2 ring-indigo-100' : ''}`}
                >
                  <span className={`grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br ${item.tone} text-white shadow-md`}><Icon size={18} /></span>
                  <div className="mt-3 flex items-center gap-1.5 text-[13px] font-semibold text-slate-900">
                    {item.title} {active && <CheckCircle2 size={13} className="text-indigo-500" />}
                  </div>
                  <div className="mt-1 text-[10px] leading-relaxed text-slate-400">{item.desc}</div>
                </button>
              )
            })}
          </div>

          <div className="card p-5">
            {method === 'template' && (
              <div>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="section-title">工作流模板</div>
                    <div className="section-desc">共 {templates.length} 个，选中后右侧会显示节点预览。</div>
                  </div>
                  <div className="relative w-full sm:w-64">
                    <Search size={14} className="absolute left-3 top-3 text-slate-400" />
                    <input className="input pl-9" placeholder="搜索模板" value={search} onChange={(event) => setSearch(event.target.value)} />
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {categories.map((item) => (
                    <button key={item} onClick={() => setCategory(item)} className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition ${category === item ? 'bg-indigo-600 text-white shadow-sm' : 'border border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:text-indigo-600'}`}>{item}</button>
                  ))}
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {filteredTemplates.map((template) => {
                    const Icon = templateIcons[template.icon as keyof typeof templateIcons] || LayoutTemplate
                    const active = templateId === template.id
                    return (
                      <button
                        key={template.id}
                        onClick={() => selectTemplate(template)}
                        className={`rounded-2xl border p-4 text-left transition ${active ? 'border-indigo-300 bg-indigo-50/40 ring-2 ring-indigo-100' : 'border-slate-200 bg-white hover:border-indigo-200 hover:bg-slate-50/60'}`}
                      >
                        <div className="flex items-start gap-3">
                          <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${active ? 'bg-indigo-600 text-white' : 'bg-indigo-50 text-indigo-600'}`}><Icon size={17} /></span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-[13px] font-semibold text-slate-900">{template.name}</span>
                              <span className="badge bg-slate-100 text-slate-600">{template.category}</span>
                            </div>
                            <div className="mt-0.5 text-[10px] text-slate-400">{template.trigger} · {template.node_count} 节点 · {template.input_count} 输入</div>
                          </div>
                          {active && <CheckCircle2 size={15} className="text-indigo-500" />}
                        </div>
                        <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{template.description}</p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {template.preview_nodes.slice(0, 4).map((node, index) => <span key={`${node.type}-${index}`} className="badge bg-white text-slate-500 ring-1 ring-slate-200">{typeLabels[node.type] || node.type}</span>)}
                          {template.preview_nodes.length > 4 && <span className="badge bg-white text-slate-400 ring-1 ring-slate-200">+{template.preview_nodes.length - 4}</span>}
                        </div>
                      </button>
                    )
                  })}
                </div>
                {!filteredTemplates.length && <div className="py-10 text-center text-[12px] text-slate-400">没有匹配的模板。</div>}
              </div>
            )}

            {method === 'blank' && (
              <div className="grid min-h-[320px] place-items-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center">
                <div>
                  <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-200"><PenLine size={24} /></span>
                  <div className="mt-4 text-[15px] font-semibold text-slate-800">从空白画布开始</div>
                  <p className="mx-auto mt-1.5 max-w-md text-[12px] leading-relaxed text-slate-500">系统会预置开始和结束节点。进入画布后从左侧节点库拖入 LLM、Agent、HTTP、审批等节点。</p>
                  <div className="mt-4 flex items-center justify-center gap-2 text-[11px] text-slate-400"><WorkflowIcon size={14} /> 适合完全自定义的流程</div>
                </div>
              </div>
            )}

            {method === 'import' && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div><div className="section-title">导入 JSON DSL</div><div className="section-desc">粘贴 FlowMind 工作流 DSL，创建后会直接进入画布。</div></div>
                  <Button variant="secondary" className="h-8 px-3 text-[11px]" onClick={() => setImportJson(JSON.stringify(sampleDsl, null, 2))}><FileJson size={13} /> 填入示例</Button>
                </div>
                <textarea className="input mt-3 min-h-[360px] font-mono text-xs" placeholder="粘贴包含 nodes / edges / inputs 的 JSON..." value={importJson} onChange={(event) => setImportJson(event.target.value)} />
                {importJson.trim() && (
                  <div className="mt-2">
                    {importParsed.error ? <Callout tone="error">{importParsed.error}</Callout> : <Callout tone="success">JSON 解析成功，共 {importParsed.nodes.length} 个节点。</Callout>}
                  </div>
                )}
              </div>
            )}

            {method === 'clone' && (
              <div>
                <div className="section-title">复制已有工作流</div>
                <div className="section-desc">保留原草稿 DSL，创建一个新的独立副本，不会影响原流程。</div>
                <div className="mt-4 grid gap-2.5 md:grid-cols-2">
                  {workflows.map((workflow) => {
                    const active = cloneId === workflow.id
                    return (
                      <button key={workflow.id} onClick={() => selectClone(workflow)} className={`rounded-2xl border p-4 text-left transition ${active ? 'border-indigo-300 bg-indigo-50/40 ring-2 ring-indigo-100' : 'border-slate-200 bg-white hover:border-indigo-200 hover:bg-slate-50/60'}`}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-[13px] font-semibold text-slate-900">{workflow.name}</div>
                            <div className="mt-0.5 text-[10px] text-slate-400">{workflow.current_version_id ? `已发布 v${workflow.version_no}` : '草稿'} · {(workflow.draft_dsl?.nodes || []).length} 节点</div>
                          </div>
                          {active && <CheckCircle2 size={15} className="text-indigo-500" />}
                        </div>
                        <div className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{workflow.description || '暂无描述'}</div>
                      </button>
                    )
                  })}
                </div>
                {!workflows.length && <EmptyState title="还没有可复制的工作流" hint="先创建一个工作流，或改用模板创建。" icon={Copy} />}
              </div>
            )}
          </div>
        </div>

        <aside className="card h-fit p-5 xl:sticky xl:top-24">
          <div className="flex items-center gap-2 section-title"><Sparkles size={16} className="text-indigo-500" /> 创建摘要</div>
          <div className="section-desc">创建后会进入画布，草稿不会自动发布。</div>

          <div className="mt-4 rounded-2xl bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">来源</span>
              <span className="badge bg-white text-indigo-700 ring-1 ring-indigo-100">{sourceLabel}</span>
            </div>
            <div className="mt-2 flex items-center gap-1.5 text-[10px] text-slate-400">
              <LayoutTemplate size={12} /> {previewNodes.length} 个节点
              {method === 'template' && selectedTemplate && <><span>·</span>{selectedTemplate.trigger}</>}
            </div>
          </div>

          <div className="mt-4 space-y-3">
            <Field label="工作流名称" hint="创建后仍可在画布顶部修改。">
              <input className="input" placeholder="例如：售后工单自动分派" value={name} onChange={(event) => setName(event.target.value)} autoFocus={method === 'blank'} />
            </Field>
            <Field label="说明（可选）">
              <textarea className="input min-h-20" placeholder="这个工作流解决什么问题？" value={description} onChange={(event) => setDescription(event.target.value)} />
            </Field>
          </div>

          <div className="mt-4">
            <div className="label">节点路径预览</div>
            <div className="flex flex-wrap items-center gap-1.5 rounded-2xl border border-slate-200 bg-white p-3">
              {previewNodes.length ? previewNodes.map((node, index) => (
                <Fragment key={`${node.type}-${index}`}>
                  <span className="rounded-lg bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{typeLabels[node.type] || node.type}</span>
                  {index < previewNodes.length - 1 && <ArrowRight size={11} className="text-slate-300" />}
                </Fragment>
              )) : <span className="text-[11px] text-slate-400">选择模板或导入 DSL 后显示节点路径</span>}
            </div>
          </div>

          {method === 'template' && selectedTemplate && (
            <div className="mt-4 space-y-1.5">
              {selectedTemplate.highlights.map((item) => (
                <div key={item} className="flex items-start gap-1.5 text-[11px] text-slate-500"><CheckCircle2 size={12} className="mt-0.5 shrink-0 text-emerald-500" /> {item}</div>
              ))}
            </div>
          )}

          <Button className="mt-5 w-full" disabled={!canCreate || !canCreateWorkflow} onClick={() => void create()}>
            {creating ? <><Loader2 size={15} className="animate-spin" /> 创建中…</> : <>创建并打开画布 <ArrowRight size={15} /></>}
          </Button>
          <div className="mt-2 text-center text-[10px] leading-relaxed text-slate-400">创建后可直接拖拽节点、校验并发布版本</div>
        </aside>
      </div>
    </div>
  )
}