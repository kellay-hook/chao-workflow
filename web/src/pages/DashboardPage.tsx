import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CheckSquare,
  Database,
  LayoutDashboard,
  PlayCircle,
  Puzzle,
  Wrench,
  Workflow as WorkflowIcon,
  Zap,
} from 'lucide-react'
import { approvalApi, knowledgeApi, resourceApi, runApi, tenantApi, workflowApi } from '../api'
import type { AgentProfile, Approval, KnowledgeBase, Run, Usage, Workflow } from '../types'
import { useSession } from '../store'
import { EmptyState, GuideSteps, PageHeader, StatCard, StatusBadge } from '../components/ui'
import { useCan } from '../components/permissions'

export default function DashboardPage() {
  const canCreateWorkflow = useCan('workflow.create')
  const canUploadKnowledge = useCan('knowledge.upload')
  const user = useSession((state) => state.user)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [agents, setAgents] = useState<AgentProfile[]>([])

  useEffect(() => {
    void Promise.all([
      tenantApi.usage(),
      workflowApi.list(),
      runApi.list(),
      approvalApi.list(),
      knowledgeApi.list(),
      resourceApi.agents(),
    ]).then(
      ([usageData, workflowData, runData, approvalData, kbData, agentData]) => {
        setUsage(usageData)
        setWorkflows(workflowData)
        setRuns(runData.slice(0, 8))
        setApprovals(approvalData)
        setKnowledgeBases(kbData)
        setAgents(agentData)
      },
    )
  }, [])

  const workflowNames = useMemo(() => new Map(workflows.map((workflow) => [workflow.id, workflow.name])), [workflows])
  const cards = [
    { label: '工作流', value: workflows.length, icon: WorkflowIcon, to: '/workflows', hint: '可编排的自动化流程', tone: 'indigo' as const },
    { label: '近 30 天运行', value: usage?.runs ?? 0, icon: PlayCircle, to: '/runs', hint: '包含手动、定时与 Webhook', tone: 'sky' as const },
    { label: '待审批', value: approvals.length, icon: CheckSquare, to: '/approvals', hint: '高风险工具调用需确认', tone: 'amber' as const },
    { label: 'Token 用量', value: usage?.llm_tokens ?? 0, icon: Zap, to: '/settings', hint: '近 30 天模型消耗', tone: 'emerald' as const },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Dashboard"
        title={`你好，${user?.name || '欢迎回来'}`}
        description="从一个清晰的工作台开始：创建流程、绑定知识与模型、发布运行，并在关键写操作前完成审批。"
        icon={LayoutDashboard}
        actions={
          <>
            {canUploadKnowledge && <Link to="/knowledge" className="btn-secondary"><Database size={15} /> 上传知识</Link>}
            {canCreateWorkflow && <Link to="/workflows/new" className="btn-primary"><WorkflowIcon size={15} /> 新建工作流</Link>}
          </>
        }
      />

      <GuideSteps
        steps={[
          { title: '创建工作流', description: '从空白画布开始，拖入开始、LLM、Agent 等节点。' },
          { title: '绑定能力', description: '在节点中选择模型、知识库、工具或审批策略。' },
          { title: '发布并运行', description: '发布版本后输入参数，查看实时执行轨迹。' },
          { title: '处理审批', description: '中高风险写操作会暂停，确认后自动继续。' },
        ]}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => <StatCard key={card.label} {...card} />)}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <div className="section-title">最近运行</div>
              <div className="section-desc">点击任意一条记录查看输出、轨迹与错误信息。</div>
            </div>
            <Link to="/runs" className="inline-flex items-center gap-1 text-[12px] font-semibold text-indigo-600 hover:text-indigo-500">
              查看全部 <ArrowRight size={13} />
            </Link>
          </div>
          {runs.length ? (
            <div className="divide-y divide-slate-100">
              {runs.map((run) => (
                <Link key={run.id} to={`/runs/${run.id}`} className="flex items-center gap-4 px-5 py-3.5 transition hover:bg-slate-50/80">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
                    <PlayCircle size={17} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold text-slate-800">{workflowNames.get(run.workflow_id) || `运行 ${run.id.slice(0, 8)}`}</div>
                    <div className="mt-0.5 truncate text-[11px] text-slate-400">
                      {new Date(run.created_at).toLocaleString()} · {run.trigger_type} · {run.token_usage} tokens
                    </div>
                  </div>
                  <StatusBadge status={run.status} />
                  <ArrowRight size={14} className="text-slate-300" />
                </Link>
              ))}
            </div>
          ) : (
            <div className="p-5">
              <EmptyState
                title="还没有运行记录"
                hint="创建并发布第一个工作流，运行后会在这里看到完整轨迹。"
                icon={WorkflowIcon}
                action={<Link to="/workflows" className="btn-primary">创建第一个工作流</Link>}
              />
            </div>
          )}
        </section>

        <div className="space-y-5">
          <section className="card p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="section-title">需要你处理</div>
                <div className="section-desc">高风险工具调用会暂停，等待确认。</div>
              </div>
              <Link to="/approvals" className="text-[12px] font-semibold text-indigo-600 hover:text-indigo-500">审批中心</Link>
            </div>
            <div className="mt-4 space-y-2.5">
              {approvals.slice(0, 4).map((approval) => (
                <Link key={approval.id} to="/approvals" className="block rounded-xl border border-amber-200/80 bg-amber-50/70 p-3 transition hover:border-amber-300 hover:bg-amber-50">
                  <div className="truncate text-[12px] font-semibold text-amber-900">{approval.title}</div>
                  <div className="mt-1 text-[11px] text-amber-700/80">{approval.tool_name || approval.node_id || '工具调用'} · {approval.risk_level}</div>
                </Link>
              ))}
              {!approvals.length && (
                <div className="flex items-center gap-2 rounded-xl bg-emerald-50 p-3 text-[12px] font-medium text-emerald-700">
                  <CheckCircle2 size={15} /> 当前没有待审批事项
                </div>
              )}
            </div>
          </section>

          <section className="card p-5">
            <div className="section-title">快捷入口</div>
            <div className="mt-4 grid grid-cols-2 gap-2.5">
              {[
                { to: '/knowledge', label: '知识库', desc: `${knowledgeBases.length} 个知识库`, icon: Database },
                { to: '/agents', label: 'Agent', desc: `${agents.length} 个智能体`, icon: Bot },
                { to: '/tools', label: '工具 / MCP', desc: 'OAuth 与 HTTP 工具', icon: Wrench },
                { to: '/plugins', label: '插件市场', desc: '安装并扩展 Agent 能力', icon: Puzzle },
              ].map((item) => {
                const Icon = item.icon
                return (
                  <Link key={item.to} to={item.to} className="rounded-xl border border-slate-200 p-3 transition hover:border-indigo-200 hover:bg-indigo-50/40">
                    <Icon size={16} className="text-indigo-500" />
                    <div className="mt-2 text-[12px] font-semibold text-slate-800">{item.label}</div>
                    <div className="mt-0.5 text-[10px] text-slate-400">{item.desc}</div>
                  </Link>
                )
              })}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}