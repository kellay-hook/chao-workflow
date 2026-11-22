import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { KeyRound } from 'lucide-react'
import { authApi } from '../api'
import { useSession } from '../store'
import { Button, Callout, Field } from '../components/ui'
import AuthLayout from '../components/AuthLayout'

export default function LoginPage() {
  const navigate = useNavigate()
  const setSession = useSession((state) => state.setSession)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  return (
    <AuthLayout
      title="登录 FlowMind"
      subtitle="继续编排工作流、调试 Agent，并处理需要人工确认的写操作。"
      footer={
        <>
          还没有账号？{' '}
          <Link className="font-semibold text-indigo-600 hover:text-indigo-500" to="/register">
            创建账号
          </Link>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          setError('')
          setLoading(true)
          try {
            const data = await authApi.login({ email, password })
            setSession(data)
            navigate('/')
          } catch (err) {
            setError(err instanceof Error ? err.message : '登录失败')
          } finally {
            setLoading(false)
          }
        }}
      >
        <Field label="邮箱">
          <input className="input" type="email" autoComplete="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="密码">
          <input className="input" type="password" autoComplete="current-password" placeholder="输入密码" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        {error && <Callout tone="error">{error}</Callout>}
        <Button className="w-full" disabled={loading} type="submit">
          {loading ? '登录中…' : '登录'}
        </Button>

        <div className="rounded-2xl border border-dashed border-indigo-200 bg-indigo-50/60 p-4">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-indigo-800">
            <KeyRound size={14} /> 演示账号
          </div>
          <div className="mt-1 text-[11px] leading-relaxed text-indigo-700/80">
            demo@flowmind.dev / password123
          </div>
          <button
            type="button"
            className="mt-3 text-[11px] font-semibold text-indigo-700 underline decoration-indigo-300 underline-offset-2 hover:text-indigo-600"
            onClick={() => {
              setEmail('demo@flowmind.dev')
              setPassword('password123')
              setError('')
            }}
          >
            一键填入演示账号
          </button>
        </div>
      </form>
    </AuthLayout>
  )
}