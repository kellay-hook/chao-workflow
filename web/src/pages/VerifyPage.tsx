import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
import { authApi } from '../api'
import AuthLayout from '../components/AuthLayout'

export default function VerifyPage() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [message, setMessage] = useState('')
  useEffect(() => {
    const token = params.get('token')
    if (!token) {
      setStatus('error')
      setMessage('缺少验证令牌')
      return
    }
    authApi
      .verify(token)
      .then(() => setStatus('ok'))
      .catch((err) => {
        setStatus('error')
        setMessage(err instanceof Error ? err.message : '验证失败')
      })
  }, [params])
  return (
    <AuthLayout title="邮箱验证" subtitle="验证完成后即可登录并开始使用工作台。">
      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-6 text-center">
        {status === 'loading' && (
          <>
            <Loader2 size={30} className="mx-auto animate-spin text-indigo-500" />
            <div className="mt-3 text-sm font-semibold text-slate-800">正在验证邮箱…</div>
            <div className="mt-1 text-[11px] text-slate-500">请稍候，不要关闭页面。</div>
          </>
        )}
        {status === 'ok' && (
          <>
            <CheckCircle2 size={32} className="mx-auto text-emerald-500" />
            <div className="mt-3 text-sm font-semibold text-slate-800">验证成功</div>
            <div className="mt-1 text-[11px] text-slate-500">现在可以登录了。</div>
          </>
        )}
        {status === 'error' && (
          <>
            <XCircle size={32} className="mx-auto text-rose-500" />
            <div className="mt-3 text-sm font-semibold text-slate-800">验证失败</div>
            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{message}</div>
          </>
        )}
      </div>
      <Link className="btn-primary mt-4 w-full" to="/login">前往登录</Link>
    </AuthLayout>
  )
}