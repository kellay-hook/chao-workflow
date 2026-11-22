import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../api'
import { useSession } from '../store'
import { Button, Callout, Field } from '../components/ui'
import AuthLayout from '../components/AuthLayout'

export default function AcceptInvitePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const setSession = useSession((state) => state.setSession)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const token = params.get('token') ?? ''
  return (
    <AuthLayout
      title="接受邀请"
      subtitle="设置姓名与密码即可加入团队工作区。"
      footer={<Link className="font-semibold text-indigo-600 hover:text-indigo-500" to="/login">返回登录</Link>}
    >
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          setError('')
          setLoading(true)
          try {
            const data = await authApi.acceptInvite(token, password, name)
            setSession(data)
            navigate('/')
          } catch (err) {
            setError(err instanceof Error ? err.message : '接受邀请失败')
          } finally {
            setLoading(false)
          }
        }}
      >
        <Field label="姓名">
          <input className="input" placeholder="你的姓名" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="密码" hint="至少 8 位。">
          <input className="input" type="password" minLength={8} placeholder="设置登录密码" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        {!token && <Callout tone="error">邀请链接缺少 token，请让管理员重新发送邀请。</Callout>}
        {error && <Callout tone="error">{error}</Callout>}
        <Button className="w-full" disabled={loading || !token}>{loading ? '加入中…' : '加入工作区'}</Button>
      </form>
    </AuthLayout>
  )
}