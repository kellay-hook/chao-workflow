import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, ExternalLink, ShieldAlert, X } from 'lucide-react'
import { approvalApi } from '../api'
import type { Approval } from '../types'
import { Button, EmptyState, GuideSteps, JsonBlock, PageHeader, StatusBadge } from '../components/ui'
import { useCan } from '../components/permissions'

const riskLabels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险', deny: '禁止执行' }
const riskStyles: Record<string, string> = {
  low: 'bg-sky-50 text-sky-700',
  medium: 'bg-amber-50 text-amber-700',
  high: 'bg-rose-50 text-rose-700',
  deny: 'bg-slate-100 text-slate-600',
}

export default function ApprovalsPage() {
  const canDecide = useCan('approval.decide')
  const [items, setItems] = useState<Approval[]>([])
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const load = () => approvalApi.list().then(setItems).catch((err) => setError(err.message))
  useEffect(() => { void load() }, [])
  const decide = async (id: string, approved: boolean) => {
    setBusyId(id)
    setError('')
    try {
      if (approved) await approvalApi.approve(id)
      else await approvalApi.reject(id, 'Rejected from approval inbox')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setBusyId('')
    }
  }
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Approvals"
        title="审批中心"
        description="中高风险写操作会暂停运行。先核对工具、参数和风险级别，再决定批准或拒绝。"
        icon={ShieldAlert}
        actions={<Button variant="secondary" onClick={() => void load()}>刷新列表</Button>}
      />

      <GuideSteps
        steps={[
          { title: '确认风险级别', description: '高风险操作通常涉及写入、删除或对外发送。' },
          { title: '核对调用参数', description: '展开参数，确认目标对象和内容符合预期。' },
          { title: '批准或拒绝', description: '批准后运行继续；拒绝会终止相关工具调用。' },
          { title: '回到运行轨迹', description: '在运行详情中查看后续节点与最终输出。' },
        ]}
      />

      {error && <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

      {!items.length ? (
        <EmptyState
          title="没有待审批事项"
          hint="当 Agent 或工作流调用中高风险工具时，会在这里等待你确认。"
          icon={ShieldAlert}
          action={<Link to="/runs" className="btn-secondary">查看运行记录</Link>}
        />
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <div key={item.id} className="card p-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-[15px] font-semibold text-slate-900">{item.title}</h2>
                    <StatusBadge status={item.status} />
                    <span className={`badge ${riskStyles[item.risk_level] || riskStyles.medium}`}>{riskLabels[item.risk_level] || item.risk_level}</span>
                  </div>
                  <p className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-slate-500">{item.description || '请核对以下工具调用参数。'}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
                    <Link className="inline-flex items-center gap-1 font-medium text-indigo-600 hover:underline" to={`/runs/${item.run_id}`}>
                      运行 {item.run_id.slice(0, 10)}… <ExternalLink size={11} />
                    </Link>
                    {item.tool_name && <span>工具：{item.tool_name}</span>}
                    {item.agent_name && <span>Agent：{item.agent_name}</span>}
                    <span>创建于 {new Date(item.created_at).toLocaleString()}</span>
                  </div>
                </div>
                {canDecide ? <div className="flex shrink-0 gap-2">
                  <Button variant="secondary" disabled={busyId === item.id} onClick={() => void decide(item.id, false)}><X size={15} /> 拒绝</Button>
                  <Button disabled={busyId === item.id} onClick={() => void decide(item.id, true)}><Check size={15} /> {busyId === item.id ? '处理中…' : '批准并继续'}</Button>
                </div> : <span className="badge bg-slate-100 text-slate-500">只读</span>}
              </div>
              <details className="group mt-4 rounded-xl border border-slate-200 bg-slate-50/60">
                <summary className="cursor-pointer list-none px-4 py-2.5 text-[11px] font-semibold text-slate-600 hover:text-slate-900">
                  查看调用参数
                </summary>
                <div className="border-t border-slate-200 p-3">
                  <JsonBlock value={item.args} />
                </div>
              </details>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}