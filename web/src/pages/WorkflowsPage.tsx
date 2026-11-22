import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Clock, LayoutTemplate, Plus, Search, Trash2, Workflow as WorkflowIcon } from 'lucide-react'
import { workflowApi } from '../api'
import type { Workflow } from '../types'
import { Callout, EmptyState, GuideSteps, PageHeader } from '../components/ui'
import { useCan } from '../components/permissions'

export default function WorkflowsPage() {
  const canCreate = useCan('workflow.create')
  const canDelete = useCan('workflow.delete')
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const load = () => workflowApi.list().then(setWorkflows).catch((err) => setError(err.message))
  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return keyword
      ? workflows.filter((workflow) => `${workflow.name} ${workflow.description}`.toLowerCase().includes(keyword))
      : workflows
  }, [workflows, search])

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Workflows"
        title="工作流"
        description="管理已创建的工作流，或进入创建工作台，从模板、空白画布、DSL 导入或已有流程副本开始。"
        icon={WorkflowIcon}
        actions={
          canCreate ? (
            <>
              <Link to="/workflows/new?mode=template" className="btn-secondary"><LayoutTemplate size={15} /> 从模板开始</Link>
              <Link to="/workflows/new" className="btn-primary"><Plus size={15} /> 新建工作流</Link>
            </>
          ) : <span className="badge bg-slate-100 text-slate-500">只读权限</span>
        }
      />

      <GuideSteps
        steps={[
          { title: '选择创建方式', description: '模板、空白、导入 DSL 或复制已有流程。' },
          { title: '预览并命名', description: '在创建工作台确认节点路径，修改名称与说明。' },
          { title: '校验并发布', description: '进入画布调整节点，校验通过后发布版本。' },
          { title: '运行与观察', description: '手动、定时或 Webhook 触发，在运行记录中查看轨迹。' },
        ]}
      />

      {error && <Callout tone="error">{error}</Callout>}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="section-title">全部工作流</div>
          <div className="section-desc">共 {workflows.length} 个，已发布 {workflows.filter((workflow) => workflow.current_version_id).length} 个。</div>
        </div>
        <div className="relative w-full sm:w-72">
          <Search size={14} className="absolute left-3 top-3 text-slate-400" />
          <input className="input pl-9" placeholder="搜索名称或描述" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>

      {!workflows.length ? (
        <EmptyState
          title="还没有工作流"
          hint="进入创建工作台，从模板或空白画布开始，几分钟即可跑通第一条流程。"
          icon={WorkflowIcon}
          action={canCreate ? <Link to="/workflows/new" className="btn-primary"><Plus size={15} /> 创建第一个工作流</Link> : undefined}
        />
      ) : !filtered.length ? (
        <EmptyState title="没有匹配的工作流" hint="换一个关键词，或清空搜索条件。" icon={Search} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((workflow) => (
            <div key={workflow.id} className="card card-hover group flex flex-col p-5">
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-indigo-50 to-violet-50 text-indigo-600 ring-1 ring-indigo-100">
                  <WorkflowIcon size={18} />
                </span>
                <Link to={`/workflows/${workflow.id}`} className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-semibold text-slate-900">{workflow.name}</div>
                  <div className="mt-1 line-clamp-2 min-h-[32px] text-[11px] leading-relaxed text-slate-500">{workflow.description || '暂无描述，进入画布后可补充节点与说明。'}</div>
                </Link>
                {canDelete && <button
                  title="删除工作流"
                  className="rounded-lg p-1.5 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100"
                  onClick={async () => {
                    if (!confirm(`删除工作流「${workflow.name}」？此操作不可撤销。`)) return
                    await workflowApi.remove(workflow.id)
                    await load()
                  }}
                >
                  <Trash2 size={15} />
                </button>}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className={`badge ${workflow.current_version_id ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                  <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
                  {workflow.current_version_id ? `已发布 v${workflow.version_no}` : '草稿'}
                </span>
                <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
                  <Clock size={11} /> {new Date(workflow.updated_at || workflow.created_at).toLocaleString()}
                </span>
              </div>

              <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
                <span className="text-[10px] text-slate-400">{(workflow.draft_dsl?.nodes || []).length} 个节点 · ID {workflow.id.slice(0, 8)}</span>
                <Link to={`/workflows/${workflow.id}`} className="inline-flex items-center gap-1 text-[12px] font-semibold text-indigo-600 hover:text-indigo-500">
                  打开画布 <ArrowRight size={13} />
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}