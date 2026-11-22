import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '../api'
import { useSession } from '../store'
import { Button, Callout, Field } from '../components/ui'
import AuthLayout from '../components/AuthLayout'

export default function RegisterPage() {
  const navigate = useNavigate()
  const setSession = useSession((state) => state.setSession)
  const [form, setForm] = useState({ name: '', email: '', password: '', tenant_name: '' })
  const [error, setError] = useState('')
  const [verificationToken, setVerificationToken] = useState('')
  const [loading, setLoading] = useState(false)
  return (
    <AuthLayout
      title="创建你的工作空间"
      subtitle="注册后会自动创建个人租户，之后可以邀请团队成员一起协作。"
      footer={
        <>
          已有账号？{' '}
          <Link className="font-semibold text-indigo-600 hover:text-indigo-500" to="/login">
            返回登录
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
            const data = await authApi.register(form)
            if (data.user.email_verified) {
              setSession(data)
              navigate('/')
              return
            }
            if (data.verification_token) setVerificationToken(data.verification_token)
            else setVerificationToken('sent')
          } catch (err) {
            setError(err instanceof Error ? err.message : '注册失败')
          } finally {
            setLoading(false)
          }
        }}
      >
        {verificationToken ? (
          <div className="space-y-4">
            <Callout tone="success" title="验证邮件已发送">
              开发环境下可以直接打开验证链接完成邮箱验证。
            </Callout>
            {verificationToken !== 'sent' && (
              <Link className="btn-primary w-full" to={`/verify?token=${encodeURIComponent(verificationToken)}`}>
                立即验证邮箱
              </Link>
            )}
            <Link className="btn-secondary w-full" to="/login">返回登录</Link>
          </div>
        ) : (
          <>
            <Field label="姓名">
              <input className="input" placeholder="例如：张三" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="邮箱">
              <input className="input" type="email" autoComplete="email" placeholder="you@company.com" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            </Field>
            <Field label="密码" hint="至少 8 位，建议同时包含字母和数字。">
              <input className="input" type="password" autoComplete="new-password" placeholder="设置登录密码" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            </Field>
            <Field label="团队 / 租户名称" hint="可以稍后在设置中修改。">
              <input className="input" placeholder="例如：增长团队" value={form.tenant_name} onChange={(e) => setForm({ ...form, tenant_name: e.target.value })} />
            </Field>
            {error && <Callout tone="error">{error}</Callout>}
            <Button className="w-full" disabled={loading} type="submit">
              {loading ? '创建中…' : '创建账号'}
            </Button>
          </>
        )}
      </form>
    </AuthLayout>
  )
}