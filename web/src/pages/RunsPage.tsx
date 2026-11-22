import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Clock, PlayCircle, RefreshCw, Search } from 'lucide-react'
import { runApi, workflowApi } from '../api'
import type { Run, Workflow } from '../types'
import { Button, EmptyState, GuideSteps, PageHeader, StatusBadge, TriggerLabel } from '../components/ui'

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'waiting_approval', label: '等待审批' },
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
]

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [runData, workflowData] = await Promise.all([
        runApi.list(status ? { run_status: status } : {}),
        workflowApi.list(),
      ])
      setRuns(runData)
      setWorkflows(workflowData)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载运行记录失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [status])

  const workflowNames = useMemo(() => new Map(workflows.map((workflow) => [workflow.id, workflow.name])), [workflows])
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return runs
    return runs.filter((run) => `${run.id} ${workflowNames.get(run.workflow_id) || ''}`.toLowerCase().includes(keyword))
  }, [runs, query, workflowNames])
  const counts = useMemo(() => ({
    total: runs.length,
    running: runs.filter((run) => run.status === 'running').length,
    waiting: runs.filter((run) => run.status === 'waiting_approval').length,
    failed: runs.filter((run) => run.status === 'failed').length,
  }), [runs])

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Runs"
        title="运行记录"
        description="每一次执行都可追溯：查看状态、触发方式、耗时、token 消耗和节点级轨迹。"
        icon={PlayCircle}
        actions={<Button variant="secondary" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> 刷新</Button>}
      />

      <GuideSteps
        steps={[
          { title: '先运行工作流', description: '在画布中发布版本，然后输入参数运行。' },
          { title: '用状态筛选', description: '快速定位失败、运行中或等待审批的记录。' },
          { title: '打开单次运行', description: '查看最终输出、执行轨迹、输入和事件流。' },
          { title: '按错误修复', description: '失败时先看节点轨迹，再回到画布调整配置。' },
        ]}
      />

      {error && <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

      <div className="grid gap-3 sm:grid-cols-4">
        {[
          { label: '当前列表', value: counts.total, cls: 'text-slate-900' },
          { label: '运行中', value: counts.running, cls: 'text-sky-600' },
          { label: '等待审批', value: counts.waiting, cls: 'text-amber-600' },
          { label: '失败', value: counts.failed, cls: 'text-rose-600' },
        ].map((item) => (
          <div key={item.label} className="card px-4 py-3">
            <div className="text-[11px] font-medium text-slate-400">{item.label}</div>
            <div className={`mt-1 text-2xl font-semibold ${item.cls}`}>{item.value}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5">
          {statusOptions.map((item) => (
            <button
              key={item.value}
              onClick={() => setStatus(item.value)}
              className={`rounded-full px-3 py-1.5 text-[12px] font-semibold transition ${status === item.value ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-200' : 'border border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:text-indigo-600'}`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="relative w-full lg:w-72">
          <Search size={14} className="absolute left-3 top-3 text-slate-400" />
          <input className="input pl-9" placeholder="搜索运行 ID 或工作流" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
      </div>

      {!filtered.length ? (
        <EmptyState
          title={runs.length ? '没有匹配的运行记录' : '暂无运行记录'}
          hint={runs.length ? '换一个关键词或状态筛选试试。' : '打开一个工作流，发布后点击运行，就能在这里看到记录。'}
          icon={PlayCircle}
          action={<Link to="/workflows" className="btn-primary">去工作流画布</Link>}
        />
      ) : (
        <div className="table-shell">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-slate-100 bg-slate-50/80 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">
              <tr>
                <th className="px-5 py-3">运行</th>
                <th className="px-5 py-3">工作流</th>
                <th className="px-5 py-3">触发</th>
                <th className="px-5 py-3">状态</th>
                <th className="px-5 py-3">Token</th>
                <th className="px-5 py-3">创建时间</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((run) => (
                <tr key={run.id} className="group transition hover:bg-indigo-50/30">
                  <td className="px-5 py-3.5 font-mono text-[11px] text-indigo-600">
                    <Link to={`/runs/${run.id}`}>{run.id.slice(0, 10)}…</Link>
                  </td>
                  <td className="max-w-[220px] px-5 py-3.5">
                    <div className="truncate text-[13px] font-medium text-slate-800">{workflowNames.get(run.workflow_id) || run.workflow_id.slice(0, 8)}</div>
                  </td>
                  <td className="px-5 py-3.5 text-slate-500"><TriggerLabel trigger={run.trigger_type} /></td>
                  <td className="px-5 py-3.5"><StatusBadge status={run.status} /></td>
                  <td className="px-5 py-3.5 text-[11px] text-slate-500">{run.token_usage.toLocaleString()}</td>
                  <td className="px-5 py-3.5 text-[11px] text-slate-500">
                    <span className="inline-flex items-center gap-1"><Clock size={12} /> {new Date(run.created_at).toLocaleString()}</span>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <Link to={`/runs/${run.id}`} className="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-600 opacity-0 transition group-hover:opacity-100">
                      详情 <ArrowRight size={12} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}