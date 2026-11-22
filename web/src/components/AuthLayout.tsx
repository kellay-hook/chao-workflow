import type { ReactNode } from 'react'
import { Bot, Database, Sparkles, Workflow } from 'lucide-react'

export default function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle: string
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="grid min-h-screen bg-[#f5f7fb] lg:grid-cols-[1.05fr_0.95fr]">
      <section className="relative hidden overflow-hidden bg-[#0b1020] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -left-24 top-20 h-72 w-72 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="absolute -right-16 bottom-10 h-80 w-80 rounded-full bg-violet-500/15 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-lg font-bold shadow-lg shadow-indigo-950/40">F</div>
            <div>
              <div className="text-[16px] font-semibold">FlowMind</div>
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">Workflow & Agents</div>
            </div>
          </div>
          <h2 className="mt-16 max-w-lg text-[40px] font-semibold leading-[1.15] tracking-[-0.03em]">
            把重复工作交给
            <span className="bg-gradient-to-r from-indigo-300 to-violet-300 bg-clip-text text-transparent"> 智能工作流</span>
          </h2>
          <p className="mt-4 max-w-md text-[14px] leading-relaxed text-slate-400">
            可视化编排、知识库检索、多 Agent 协作与人工审批，都在一个清晰的工作台里完成。
          </p>
        </div>

        <div className="relative grid max-w-lg gap-3">
          {[
            { icon: Workflow, title: '可视化编排', desc: '拖拽节点，连成可运行、可复用的自动化流程。' },
            { icon: Database, title: '知识与引用', desc: '上传资料即可检索，回答附带来源分块。' },
            { icon: Bot, title: 'Agent 与审批', desc: '工具调用可追溯，高风险写操作先审批。' },
          ].map((item) => {
            const Icon = item.icon
            return (
              <div key={item.title} className="flex items-start gap-3 rounded-2xl border border-white/[0.07] bg-white/[0.04] p-4">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-indigo-500/20 text-indigo-200">
                  <Icon size={17} />
                </span>
                <div>
                  <div className="text-[13px] font-semibold">{item.title}</div>
                  <div className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{item.desc}</div>
                </div>
              </div>
            )
          })}
        </div>

        <div className="relative flex items-center gap-2 text-[11px] text-slate-500">
          <Sparkles size={14} /> 从一条工作流开始，10 分钟体验完整闭环
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center p-5 sm:p-8">
        <div className="w-full max-w-[430px]">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-lg font-bold text-white shadow-lg shadow-indigo-200">F</div>
            <div>
              <div className="text-sm font-semibold text-slate-900">FlowMind</div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Workflow & Agents</div>
            </div>
          </div>
          <div className="rounded-[28px] border border-slate-200/80 bg-white p-6 shadow-[0_2px_6px_rgba(15,23,42,0.04),0_32px_80px_-40px_rgba(15,23,42,0.35)] sm:p-8">
            <div className="page-eyebrow">Welcome</div>
            <h1 className="mt-1 text-[26px] font-semibold tracking-[-0.02em] text-slate-950">{title}</h1>
            <p className="mt-2 text-[13px] leading-relaxed text-slate-500">{subtitle}</p>
            <div className="mt-7">{children}</div>
          </div>
          {footer && <div className="mt-6 text-center text-[12px] text-slate-500">{footer}</div>}
        </div>
      </section>
    </div>
  )
}