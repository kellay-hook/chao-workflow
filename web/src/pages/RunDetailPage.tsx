import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Ban, CheckCircle2, Clock, Copy, Cpu, ExternalLink, PlayCircle, RotateCcw, XCircle } from 'lucide-react'
import { runApi, subscribeRun } from '../api'
import type { NodeRun, Run } from '../types'
import { Button, Callout, EmptyState, StatusBadge, TriggerLabel } from '../components/ui'
import { useCan } from '../components/permissions'
import JsonViewer from '../components/JsonViewer'

type Tab = 'result' | 'trace' | 'input' | 'events'

function duration(run: Run): string {
  if (!run.started_at) return '-'
  const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now()
  const ms = end - new Date(run.started_at).getTime()
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

function NodeIcon({ status }: { status: string }) {
  if (status === 'succeeded') return <CheckCircle2 size={18} className="text-emerald-500" />
  if (status === 'failed') return <XCircle size={18} className="text-rose-500" />
  if (status === 'waiting_approval') return <AlertTriangle size={18} className="text-amber-500" />
  if (status === 'running') return <PlayCircle size={18} className="text-sky-500" />
  return <Clock size={18} className="text-slate-400" />
}

export default function RunDetailPage() {
  const canRetry = useCan('run.retry')
  const canCancel = useCan('run.cancel')
  const { id = '' } = useParams()
  const [run, setRun] = useState<Run | null>(null)
  const [nodes, setNodes] = useState<NodeRun[]>([])
  const [events, setEvents] = useState<{ event: string; data: any; at: string }[]>([])
  const [tab, setTab] = useState<Tab>('result')
  const [error, set错误] = useState('')
  const [copied, setCopied] = useState(false)

  const refresh = async () => {
    const [runData, nodeData] = await Promise.all([runApi.get(id), runApi.nodes(id)])
    setRun(runData)
    setNodes(nodeData)
  }

  useEffect(() => {
    void refresh().catch((err) => set错误(err.message))
    let cleanup: (() => void) | undefined
    void subscribeRun(id, (event) => {
      setEvents((current) => [...current.slice(-199), { event: event.event, data: event.data, at: new Date().toLocaleTimeString() }])
      if (event.event.startsWith('run.') || event.event.startsWith('node.')) void refresh()
    }).then((stop) => { cleanup = stop })
    return () => cleanup?.()
  }, [id])

  const latestNodes = useMemo(() => {
    const map = new Map<string, NodeRun>()
    for (const node of nodes) map.set(node.node_id, node)
    return Array.from(map.values())
  }, [nodes])

  const errorMessage = run?.error ? String(run.error.message || run.error.type || run.error) : ''
  const copyRunId = async () => {
    try {
      await navigator.clipboard.writeText(id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }

  if (error) return (
    <div className="space-y-4">
      <Callout tone="error" title="无法加载运行记录">{error}</Callout>
      <Link to="/runs" className="btn-secondary">返回运行记录</Link>
    </div>
  )
  if (!run) return (
    <div className="card grid min-h-[320px] place-items-center p-8">
      <div className="text-center">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
        <div className="mt-3 text-sm font-medium text-slate-600">正在加载运行记录…</div>
      </div>
    </div>
  )

  const tabs: { id: Tab; label: string }[] = [
    { id: 'result', label: '结果' },
    { id: 'trace', label: `执行轨迹 (${latestNodes.length})` },
    { id: 'input', label: '输入' },
    { id: 'events', label: `事件 (${events.length})` },
  ]
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-5 border-b border-slate-200/70 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <Link to="/runs" className="inline-flex items-center gap-1 text-[12px] font-medium text-slate-500 hover:text-slate-800"><ArrowLeft size={13} /> 返回运行记录</Link>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h1 className="text-[24px] font-semibold tracking-[-0.02em] text-slate-950">运行详情</h1>
            <StatusBadge status={run.status} />
            <button className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 font-mono text-[10px] text-slate-500 shadow-sm hover:bg-slate-50" onClick={copyRunId}>
              {copied ? <CheckCircle2 size={12} className="text-emerald-600" /> : <Copy size={12} />} {run.id.slice(0, 12)}…
            </button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <Link className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700 hover:bg-indigo-100" to={`/workflows/${run.workflow_id}`}>打开工作流 <ExternalLink size={12} /></Link>
            <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200"><Cpu size={12} /> {run.token_usage.toLocaleString()} tokens</span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200"><Clock size={12} /> {duration(run)}</span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200"><TriggerLabel trigger={run.trigger_type} /></span>
            <span className="text-slate-400">{new Date(run.created_at).toLocaleString()}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {canRetry && <Button variant="secondary" onClick={async () => { const next = await runApi.retry(run.id); window.location.href = `/runs/${next.id}` }}><RotateCcw size={15} /> 再次运行</Button>}
          {canCancel && ['queued', 'running', 'waiting_approval'].includes(run.status) && (
            <Button variant="danger" onClick={async () => { await runApi.cancel(run.id); await refresh() }}><Ban size={15} /> 取消运行</Button>
          )}
        </div>
      </div>

      {run.status === 'failed' && (
        <Callout tone="error" title="运行失败">
          <div className="whitespace-pre-wrap">{errorMessage || '工作流未完成。'}</div>
          <div className="mt-1 text-[11px] text-rose-600">请检查输入或节点配置后重试，切换到执行轨迹查看具体节点。</div>
        </Callout>
      )}
      {run.status === 'waiting_approval' && (
        <Callout tone="warning" title="等待人工审批">
          本次运行已暂停，请前往 <Link className="font-semibold underline" to="/approvals">审批中心</Link> 核对参数并批准或拒绝。
        </Callout>
      )}

      <div className="flex gap-1 border-b border-slate-200">
        {tabs.map((item) => (
          <button key={item.id} onClick={() => setTab(item.id)} className={`tab-btn ${tab === item.id ? 'tab-btn-active' : ''}`}>{item.label}</button>
        ))}
      </div>

      {tab === 'result' && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="card p-5">
            <div className="mb-4"><div className="section-title">最终输出</div><div className="section-desc">结构化视图，可切换原始 JSON 或复制。</div></div>
            <JsonViewer value={run.output} empty="本次运行没有产生输出。" />
          </div>
          <div className="space-y-4">
            <div className="card p-4">
              <div className="mb-3 section-title">运行概览</div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">状态</span><StatusBadge status={run.status} /></div>
                <div className="flex justify-between"><span className="text-slate-500">Token</span><span>{run.token_usage}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">耗时</span><span>{duration(run)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">触发方式</span><TriggerLabel trigger={run.trigger_type} /></div>
                <div className="flex justify-between"><span className="text-slate-500">父运行</span><span className="font-mono text-xs">{run.parent_run_id ? run.parent_run_id.slice(0, 8) : '-'}</span></div>
              </div>
            </div>
            <div className="card p-4">
              <div className="mb-2 section-title">错误</div>
              {run.error ? <div className="whitespace-pre-wrap rounded-lg bg-rose-50 p-3 text-xs text-rose-700">{errorMessage}</div> : <div className="text-sm text-slate-500">无错误。</div>}
            </div>
          </div>
        </div>
      )}

      {tab === 'trace' && (
        <div className="space-y-3">
          {latestNodes.map((node) => (
            <details key={node.id} className="card card-hover overflow-hidden" open>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50">
                <div className="flex min-w-0 items-center gap-3">
                  <NodeIcon status={node.status} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2"><span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{node.node_type}</span><span className="truncate font-medium">{node.node_id}</span></div>
                    <div className="mt-0.5 text-xs text-slate-500">{node.tokens} Token / 第 {node.attempt} / {node.finished_at ? new Date(node.finished_at).toLocaleTimeString() : '运行中'}</div>
                  </div>
                </div>
                <StatusBadge status={node.status} />
              </summary>
              <div className="grid gap-4 border-t border-slate-100 bg-slate-50/50 p-4 xl:grid-cols-2">
                <div><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">输入</div><JsonViewer value={node.input} empty="无输入" /></div>
                <div><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">输出</div><JsonViewer value={node.output} empty="无输出" /></div>
                {node.error && <div className="xl:col-span-2"><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-rose-400">错误</div><div className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700">{JSON.stringify(node.error, null, 2)}</div></div>}
              </div>
            </details>
          ))}
          {!latestNodes.length && <EmptyState title="暂无节点轨迹" hint="运行尚未开始或仍在队列中。" />}
        </div>
      )}

      {tab === 'input' && (
        <div className="card p-5"><h2 className="mb-3 font-semibold">运行输入</h2><JsonViewer value={run.inputs} empty="无输入" /></div>
      )}

      {tab === 'events' && (
        <div className="card p-5">
          <h2 className="mb-3 font-semibold">实时事件</h2>
          <div className="max-h-[620px] space-y-2 overflow-auto">
            {events.map((event, index) => (
              <div key={index} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-xs">
                <div className="flex justify-between text-slate-500"><span className="font-mono">{event.event}</span><span>{event.at}</span></div>
                <pre className="mt-1 whitespace-pre-wrap break-words text-slate-700">{JSON.stringify(event.data, null, 2)}</pre>
              </div>
            ))}
            {!events.length && <div className="py-8 text-center text-sm text-slate-400">暂无事件。</div>}
          </div>
        </div>
      )}
    </div>
  )
}
