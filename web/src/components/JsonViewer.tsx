import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-react'

function valueClass(value: unknown): string {
  if (value === null) return 'text-slate-400'
  if (typeof value === 'boolean') return value ? 'text-emerald-600' : 'text-rose-600'
  if (typeof value === 'number') return 'text-sky-600'
  return 'text-slate-700'
}

function ValueView({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="text-slate-400">null</span>
  if (typeof value === 'string') {
    if (value.startsWith('http://') || value.startsWith('https://')) {
      return <a className="break-all text-indigo-600 underline" href={value} target="_blank" rel="noreferrer">{value}</a>
    }
    return <span className="whitespace-pre-wrap break-words text-slate-700">{value}</span>
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return <span className={valueClass(value)}>{String(value)}</span>
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-slate-400">[]</span>
    return (
      <div className="space-y-1.5">
        {value.map((item, index) => (
          <div key={index} className="flex gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5">
            <span className="mt-0.5 shrink-0 font-mono text-[10px] text-slate-400">{index}</span>
            <div className="min-w-0 flex-1"><ValueView value={item} depth={depth + 1} /></div>
          </div>
        ))}
      </div>
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (!entries.length) return <span className="text-slate-400">{'{}'}</span>
    return (
      <div className="space-y-2">
        {entries.map(([key, item]) => (
          <div key={key}>
            <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{key}</div>
            <div className="rounded-lg border border-slate-100 bg-white px-2.5 py-1.5"><ValueView value={item} depth={depth + 1} /></div>
          </div>
        ))}
      </div>
    )
  }
  return <span className="text-slate-700">{String(value)}</span>
}

export default function JsonViewer({ value, empty = '暂无数据' }: { value: unknown; empty?: string }) {
  const [raw, setRaw] = useState(false)
  const [copied, setCopied] = useState(false)
  const hasValue = value !== null && value !== undefined && !(typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(value, null, 2))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }
  if (!hasValue) return <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">{empty}</div>
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/80 px-3 py-2">
        <button className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800" onClick={() => setRaw(!raw)}>
          {raw ? <ChevronDown size={13} /> : <ChevronRight size={13} />} {raw ? '结构化视图' : '原始 JSON'}
        </button>
        <button className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-white hover:text-slate-800" onClick={copy}>
          {copied ? <Check size={13} className="text-emerald-600" /> : <Copy size={13} />} {copied ? '已复制' : '复制'}
        </button>
      </div>
      <div className="max-h-[520px] overflow-auto p-3 text-sm">
        {raw ? <pre className="whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 text-xs leading-relaxed text-slate-100">{JSON.stringify(value, null, 2)}</pre> : <ValueView value={value} />}
      </div>
    </div>
  )
}
