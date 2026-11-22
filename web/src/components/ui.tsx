import clsx from 'clsx'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Compass, Info, LucideIcon, Sparkles } from 'lucide-react'

export function Button({
  children,
  variant = 'primary',
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' }) {
  const variants = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    danger: 'btn-danger',
    ghost: 'btn text-slate-600 hover:bg-slate-100',
  }
  return (
    <button className={clsx(variants[variant], className)} {...props}>
      {children}
    </button>
  )
}

const statusLabels: Record<string, string> = {
  queued: '排队中', running: '运行中', waiting_approval: '等待审批', succeeded: '成功', failed: '失败',
  canceled: '已取消', timed_out: '超时', pending: '待处理', ready: '就绪', processing: '处理中',
  approved: '已批准', rejected: '已拒绝', expired: '已过期',
}

const triggerLabels: Record<string, string> = {
  manual: '手动', schedule: '定时', webhook: 'Webhook', retry: '重试', subworkflow: '子工作流', loop: '循环',
}

const colors: Record<string, string> = {
  queued: 'bg-slate-100 text-slate-600',
  running: 'bg-sky-100 text-sky-700',
  waiting_approval: 'bg-amber-100 text-amber-700',
  succeeded: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-rose-100 text-rose-700',
  canceled: 'bg-slate-200 text-slate-600',
  timed_out: 'bg-orange-100 text-orange-700',
  pending: 'bg-amber-100 text-amber-700',
  ready: 'bg-emerald-100 text-emerald-700',
  processing: 'bg-sky-100 text-sky-700',
  approved: 'bg-emerald-100 text-emerald-700',
  rejected: 'bg-rose-100 text-rose-700',
  expired: 'bg-slate-200 text-slate-600',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={clsx('badge', colors[status] ?? 'bg-slate-100 text-slate-600')}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {statusLabels[status] ?? status}
    </span>
  )
}

export function TriggerLabel({ trigger }: { trigger: string }) {
  return <span>{triggerLabels[trigger] ?? trigger}</span>
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-3 text-xs leading-relaxed text-slate-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function EmptyState({
  title,
  hint,
  icon: Icon = Sparkles,
  action,
}: {
  title: string
  hint?: string
  icon?: LucideIcon
  action?: ReactNode
}) {
  return (
    <div className="card grid place-items-center px-6 py-14 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-indigo-50 to-violet-50 text-indigo-500 ring-1 ring-indigo-100">
        <Icon size={24} />
      </span>
      <div className="mt-4 text-sm font-semibold text-slate-800">{title}</div>
      {hint && <div className="mt-1.5 max-w-md text-xs leading-relaxed text-slate-500">{hint}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  icon: Icon,
  actions,
}: {
  eyebrow?: string
  title: string
  description?: string
  icon?: LucideIcon
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-5 border-b border-slate-200/70 pb-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="flex items-start gap-4">
        {Icon && (
          <span className="mt-0.5 grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-200/70">
            <Icon size={22} />
          </span>
        )}
        <div className="min-w-0">
          {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
          <h1 className="page-title">{title}</h1>
          {description && <p className="page-desc">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 lg:justify-end">{actions}</div>}
    </div>
  )
}

export function SectionHeading({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <div className="section-title">{title}</div>
        {description && <div className="section-desc">{description}</div>}
      </div>
      {action}
    </div>
  )
}

export function GuideSteps({
  steps,
  title = '推荐操作路径',
}: {
  steps: { title: string; description?: string }[]
  title?: string
}) {
  return (
    <div className="rounded-[20px] border border-indigo-100 bg-gradient-to-r from-indigo-50/90 via-white to-violet-50/70 p-4 sm:p-5">
      <div className="flex items-center gap-2 text-[12px] font-bold text-indigo-700">
        <Compass size={15} /> {title}
      </div>
      <ol className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => (
          <li key={step.title} className="flex gap-3 rounded-xl bg-white/70 p-3 ring-1 ring-white">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-indigo-600 text-[12px] font-bold text-white shadow-sm shadow-indigo-200">
              {index + 1}
            </span>
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-slate-800">{step.title}</div>
              {step.description && <div className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{step.description}</div>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

const calloutStyles = {
  info: { wrap: 'border-sky-200 bg-sky-50 text-sky-800', icon: Info },
  success: { wrap: 'border-emerald-200 bg-emerald-50 text-emerald-800', icon: CheckCircle2 },
  warning: { wrap: 'border-amber-200 bg-amber-50 text-amber-800', icon: AlertCircle },
  error: { wrap: 'border-rose-200 bg-rose-50 text-rose-800', icon: AlertCircle },
}

export function Callout({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: keyof typeof calloutStyles
  title?: string
  children?: ReactNode
  action?: ReactNode
}) {
  const style = calloutStyles[tone]
  const Icon = style.icon
  return (
    <div className={clsx('flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm', style.wrap)}>
      <Icon size={17} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={clsx(title && 'mt-0.5', 'text-[13px] leading-relaxed opacity-90')}>{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div>
      <div className="label">{label}</div>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'indigo',
  to,
}: {
  label: string
  value: string | number
  hint?: string
  icon: LucideIcon
  tone?: 'indigo' | 'sky' | 'emerald' | 'amber'
  to?: string
}) {
  const tones = {
    indigo: 'from-indigo-500 to-violet-500 shadow-indigo-200',
    sky: 'from-sky-500 to-cyan-500 shadow-sky-200',
    emerald: 'from-emerald-500 to-teal-500 shadow-emerald-200',
    amber: 'from-amber-500 to-orange-500 shadow-amber-200',
  }
  const content = (
    <div className="card card-hover flex min-h-[132px] flex-col justify-between p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12px] font-semibold text-slate-500">{label}</span>
        <span className={clsx('grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br text-white shadow-md', tones[tone])}>
          <Icon size={17} />
        </span>
      </div>
      <div>
        <div className="text-[28px] font-semibold tracking-[-0.03em] text-slate-950">{typeof value === 'number' ? value.toLocaleString() : value}</div>
        {hint && <div className="mt-1 text-[11px] text-slate-400">{hint}</div>}
      </div>
    </div>
  )
  if (!to) return content
  return <Link to={to}>{content}</Link>
}