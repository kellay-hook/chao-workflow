import { useEffect, useMemo, useState } from 'react'
import { KeyRound, Lock, Pencil, Plus, RefreshCw, Settings as SettingsIcon, ShieldCheck, Trash2, UserCog, Users } from 'lucide-react'
import { resourceApi, tenantApi } from '../api'
import type { Membership, ModelProfile, RoleInfo, Usage } from '../types'
import { Button, Callout, Field, PageHeader } from '../components/ui'
import { RoleBadge, roleName } from '../components/permissions'
import { useSession } from '../store'

type Tab = '模型' | '密钥' | '成员' | '权限' | '审计'

const roleTone: Record<string, string> = {
  owner: 'border-amber-200 bg-amber-50/60',
  admin: 'border-indigo-200 bg-indigo-50/60',
  editor: 'border-sky-200 bg-sky-50/60',
  runner: 'border-emerald-200 bg-emerald-50/60',
  viewer: 'border-slate-200 bg-slate-50/60',
}

const permissionLabels: Record<string, string> = {
  'workspace.read': '查看工作空间',
  'member.read': '查看成员',
  'member.invite': '邀请成员',
  'member.update': '修改成员角色',
  'member.remove': '移除成员',
  'workflow.read': '查看工作流',
  'workflow.create': '创建工作流',
  'workflow.update': '编辑工作流',
  'workflow.delete': '删除工作流',
  'workflow.publish': '发布工作流',
  'workflow.run': '运行工作流',
  'run.read': '查看运行记录',
  'run.cancel': '取消运行',
  'run.retry': '重试运行',
  'approval.read': '查看审批',
  'approval.decide': '处理审批',
  'knowledge.read': '查看知识库',
  'knowledge.write': '编辑知识库',
  'knowledge.upload': '上传文档',
  'agent.read': '查看 Agent',
  'agent.run': '运行 Agent',
  'agent.write': '编辑 Agent',
  'agent.test': '调试 Agent',
  'tool.read': '查看工具',
  'tool.write': '管理工具/MCP',
  'tool.test': '测试工具',
  'plugin.read': '查看插件',
  'plugin.install': '安装插件',
  'plugin.uninstall': '卸载插件',
  'plugin.test': '测试插件',
  'model.read': '查看模型',
  'model.manage': '管理模型与凭据',
  'secret.manage': '管理密钥',
  'audit.read': '查看审计日志',
  'usage.read': '查看用量',
  'apikey.manage': '管理 API Key',
  'settings.read': '查看设置',
  'settings.update': '修改工作空间设置',
}

const defaultModelForm = {
  name: '',
  provider: 'openai_compatible',
  base_url: 'https://api.deepseek.com/v1',
  model: 'deepseek-chat',
  api_key: '',
  api_key_secret: '',
  is_default: true,
  max_tokens: 2048,
  temperature: 0.2,
  timeout_sec: 120,
}

export default function SettingsPage() {
  const { user, role, roles, permissions, canManageMembers, invitableRoles, refreshPermissions } = useSession()
  const allowed = (permission: string) => permissions.includes('*') || permissions.includes(permission)
  const [tab, setTab] = useState<Tab>('模型')
  const [models, setModels] = useState<ModelProfile[]>([])
  const [secrets, setSecrets] = useState<any[]>([])
  const [members, setMembers] = useState<Membership[]>([])
  const [memberRoles, setMemberRoles] = useState<Record<string, string>>({})
  const [audit, setAudit] = useState<any[]>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [editingModelId, setEditingModelId] = useState<string | null>(null)
  const [modelForm, setModelForm] = useState(defaultModelForm)
  const [secretForm, setSecretForm] = useState({ name: '', value: '' })
  const [invite, setInvite] = useState({ email: '', role: 'editor' })
  const tabs = useMemo(() => {
    const items: { id: Tab; label: string }[] = [
      { id: '模型', label: '模型' },
      { id: '密钥', label: '密钥' },
      { id: '成员', label: '成员' },
      { id: '权限', label: '权限' },
      { id: '审计', label: '审计' },
    ]
    return items.filter((item) => {
      if (item.id === '密钥') return allowed('secret.manage')
      if (item.id === '成员') return allowed('member.read')
      if (item.id === '审计') return allowed('audit.read')
      return true
    })
  }, [permissions])

  useEffect(() => {
    if (!tabs.some((item) => item.id === tab)) setTab('模型')
  }, [tabs, tab])

  useEffect(() => {
    if (invitableRoles.length && !invitableRoles.includes(invite.role)) {
      setInvite((current) => ({ ...current, role: invitableRoles[0] }))
    }
  }, [invitableRoles, invite.role])

  const load = async () => {
    const [modelData, secretData, memberData, auditData, usageData] = await Promise.all([
      resourceApi.models().catch(() => []),
      resourceApi.secrets().catch(() => []),
      tenantApi.members().catch(() => []),
      tenantApi.audit().catch(() => []),
      tenantApi.usage().catch(() => null),
    ])
    setModels(modelData)
    setSecrets(secretData)
    setMembers(memberData)
    setMemberRoles(Object.fromEntries(memberData.map((member) => [member.user_id, member.role])))
    setAudit(auditData)
    setUsage(usageData)
  }
  useEffect(() => { void load().catch((err) => setError(err.message)) }, [])
  useEffect(() => { void refreshPermissions() }, [])
  const resetModelForm = () => {
    setEditingModelId(null)
    setModelForm(defaultModelForm)
  }
  const applyPreset = (preset: 'deepseek' | 'openai' | 'ollama') => {
    if (preset === 'deepseek') {
      setModelForm((current) => ({ ...current, name: current.name || 'DeepSeek', provider: 'openai_compatible', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' }))
    } else if (preset === 'openai') {
      setModelForm((current) => ({ ...current, name: current.name || 'OpenAI', provider: 'openai_compatible', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' }))
    } else {
      setModelForm((current) => ({ ...current, name: current.name || 'Ollama', provider: 'ollama', base_url: 'http://localhost:11434/v1', model: 'qwen2.5:7b' }))
    }
  }
  const editModel = (model: ModelProfile) => {
    setEditingModelId(model.id)
    setModelForm({
      name: model.name,
      provider: model.provider,
      base_url: model.base_url,
      model: model.model,
      api_key: '',
      api_key_secret: '',
      is_default: model.is_default,
      max_tokens: model.max_tokens,
      temperature: model.temperature,
      timeout_sec: model.timeout_sec,
    })
  }
  const saveModel = async () => {
    setError('')
    setMessage('')
    try {
      const payload = { ...modelForm, embedding_dimension: 1024 }
      if (editingModelId) {
        await resourceApi.updateModel(editingModelId, payload)
        setMessage('模型配置已更新')
      } else {
        await resourceApi.createModel(payload)
        setMessage('模型配置已创建')
      }
      resetModelForm()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存模型配置失败')
    }
  }

  const inviteRoleOptions = invitableRoles.length ? invitableRoles : ['editor', 'runner', 'viewer']
  const currentRoleInfo = roles.find((item) => item.id === role)

  const canEditMember = (member: Membership) => {
    if (!allowed('member.update') || member.role === 'owner' || member.user_id === user?.id) return false
    if (role !== 'owner' && (member.role === 'admin' || memberRoles[member.user_id] === 'admin')) return false
    return true
  }

  const canRemoveMember = (member: Membership) => {
    if (!allowed('member.remove') || member.role === 'owner' || member.user_id === user?.id) return false
    if (role !== 'owner' && member.role === 'admin') return false
    return true
  }

  const saveMemberRole = async (member: Membership) => {
    const nextRole = memberRoles[member.user_id]
    if (!nextRole || nextRole === member.role) return
    setError('')
    try {
      await tenantApi.updateMemberRole(member.user_id, nextRole)
      setMessage(`已将 ${member.name || member.email} 的角色改为${roleName(nextRole, roles)}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '修改成员角色失败')
    }
  }

  const removeMember = async (member: Membership) => {
    if (!window.confirm(`将 ${member.name || member.email} 移出当前工作空间？`)) return
    setError('')
    try {
      await tenantApi.removeMember(member.user_id)
      setMessage('成员已移除')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '移除成员失败')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="设置"
        description="管理模型网关、租户密钥、团队成员与审计日志。建议先配置一个默认 Chat 模型。"
        icon={SettingsIcon}
        actions={<Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /> 刷新</Button>}
      />
      {error && <Callout tone="error">{error}</Callout>}
      {message && <Callout tone="success">{message}</Callout>}
      <div className="flex w-fit flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm">
        {tabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`rounded-xl px-4 py-2 text-[12px] font-semibold transition ${tab === item.id ? 'bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-sm shadow-indigo-200' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'}`}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === '模型' && (
        <div className="space-y-4">
          {!allowed('model.manage') && <Callout tone="info" title="模型配置为只读">当前角色可以查看模型，但只有管理员和所有者可以新增、编辑或测试模型凭据。</Callout>}
          <div className={`grid gap-6 ${allowed('model.manage') ? 'xl:grid-cols-5' : ''}`}>
          {allowed('model.manage') && <div className="card space-y-3 p-5 xl:col-span-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-semibold"><Plus size={16} /> {editingModelId ? '编辑模型配置' : '新建模型配置'}</div>
              {editingModelId && <Button variant="ghost" onClick={resetModelForm}>取消</Button>}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => applyPreset('deepseek')}>DeepSeek</Button>
              <Button variant="secondary" onClick={() => applyPreset('openai')}>OpenAI</Button>
              <Button variant="secondary" onClick={() => applyPreset('ollama')}>Ollama</Button>
            </div>
            <Field label="配置名称" hint="用于在 Agent 与节点中识别这个模型。">
              <input className="input" placeholder="例如：DeepSeek 生产" value={modelForm.name} onChange={(e) => setModelForm({ ...modelForm, name: e.target.value })} />
            </Field>
            <Field label="Provider">
              <select className="input" value={modelForm.provider} onChange={(e) => setModelForm({ ...modelForm, provider: e.target.value })}>
                <option value="openai_compatible">OpenAI 兼容</option>
                <option value="ollama">Ollama</option>
              </select>
            </Field>
            <Field label="Base URL" hint="DeepSeek 使用 https://api.deepseek.com/v1">
              <input className="input" placeholder="https://api.deepseek.com/v1" value={modelForm.base_url} onChange={(e) => setModelForm({ ...modelForm, base_url: e.target.value })} />
            </Field>
            <Field label="模型名称" hint="例如 deepseek-chat、gpt-4o-mini、qwen2.5:7b。">
              <input className="input" placeholder="deepseek-chat" value={modelForm.model} onChange={(e) => setModelForm({ ...modelForm, model: e.target.value })} />
            </Field>
            <Field label="API Key" hint={editingModelId ? '留空表示保留现有密钥。' : '密钥会加密保存，不会通过接口返回。'}>
              <input className="input" type="password" placeholder={editingModelId ? '留空保留现有密钥' : '粘贴 API Key'} value={modelForm.api_key} onChange={(e) => setModelForm({ ...modelForm, api_key: e.target.value })} />
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label="最大 Token"><input className="input" type="number" value={modelForm.max_tokens} onChange={(e) => setModelForm({ ...modelForm, max_tokens: Number(e.target.value) })} /></Field>
              <Field label="温度"><input className="input" type="number" step="0.1" value={modelForm.temperature} onChange={(e) => setModelForm({ ...modelForm, temperature: Number(e.target.value) })} /></Field>
              <Field label="超时（秒）"><input className="input" type="number" value={modelForm.timeout_sec} onChange={(e) => setModelForm({ ...modelForm, timeout_sec: Number(e.target.value) })} /></Field>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={modelForm.is_default} onChange={(e) => setModelForm({ ...modelForm, is_default: e.target.checked })} /> 设为默认模型</label>
            <Button disabled={!modelForm.name.trim() || !modelForm.base_url.trim() || !modelForm.model.trim()} onClick={saveModel}>{editingModelId ? '保存修改' : '添加模型'}</Button>
            <p className="text-xs leading-relaxed text-slate-500">API Key 会作为加密租户密钥保存。DeepSeek 的 Base URL 为 https://api.deepseek.com/v1，模型为 deepseek-chat。</p>
          </div>}
          <div className={`space-y-4 ${allowed('model.manage') ? 'xl:col-span-3' : ''}`}>
            {models.map((model) => (
              <div key={model.id} className="card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold">{model.name} {model.is_default && <span className="badge ml-2 bg-indigo-100 text-indigo-700">默认</span>}</div>
                    <div className="mt-1 text-sm text-slate-500">{model.provider} · {model.model}</div>
                    <div className="truncate text-xs text-slate-400">{model.base_url}</div>
                    <div className="mt-1 text-xs text-slate-400">{model.has_api_key ? '已配置 API Key' : '未配置 API Key'}</div>
                  </div>
                  {allowed('model.manage') && <div className="flex gap-2">
                    <Button variant="secondary" onClick={async () => {
                      const result = await resourceApi.testModel(model.id)
                      setMessage(result.ok ? `连接正常：${result.content ?? ''}` : `连接失败：${result.error ?? '未知错误'}`)
                    }}><RefreshCw size={15} /> 测试连接</Button>
                    <Button variant="secondary" onClick={() => editModel(model)}><Pencil size={15} /> 编辑</Button>
                    <Button variant="danger" onClick={async () => { if (!confirm(`删除模型配置「${model.name}」？`)) return; await resourceApi.deleteModel(model.id); await load() }}><Trash2 size={16} /></Button>
                  </div>}
                </div>
              </div>
            ))}
            {!models.length && <div className="card p-10 text-center text-sm text-slate-500">还没有模型配置。可以在上方选择 DeepSeek、OpenAI 或 Ollama 预设。</div>}
            {usage && <div className="card p-5 text-sm text-slate-600">近 30 天：{usage.runs} 次运行 · {usage.llm_tokens} tokens</div>}
          </div>
          </div>
        </div>
      )}

      {tab === '密钥' && (
        <div className="grid gap-6 xl:grid-cols-3">
          <div className="card space-y-3 p-5">
            <div className="flex items-center gap-2 font-semibold"><KeyRound size={16} /> 新建租户密钥</div>
            <Field label="密钥名称" hint="在工具或节点中用 secret 引用这个名称。"><input className="input" placeholder="例如：stripe_key" value={secretForm.name} onChange={(e) => setSecretForm({ ...secretForm, name: e.target.value })} /></Field>
            <Field label="密钥值"><textarea className="input min-h-24" placeholder="粘贴密钥内容" value={secretForm.value} onChange={(e) => setSecretForm({ ...secretForm, value: e.target.value })} /></Field>
            <Button disabled={!secretForm.name.trim() || !secretForm.value} onClick={async () => {
              try {
                await resourceApi.createSecret(secretForm.name, secretForm.value)
                setSecretForm({ name: '', value: '' })
                setMessage('密钥已保存')
                await load()
              } catch (err) { setError(err instanceof Error ? err.message : '保存失败') }
            }}>保存</Button>
          </div>
          <div className="space-y-4 xl:col-span-2">
            {secrets.map((secret) => (
              <div key={secret.id} className="card flex items-center justify-between p-4">
                <div className="font-mono text-sm">{secret.name}</div>
                <Button variant="danger" onClick={async () => { await resourceApi.deleteSecret(secret.id); await load() }}>删除</Button>
              </div>
            ))}
            {!secrets.length && <div className="card p-10 text-center text-sm text-slate-500">还没有密钥。</div>}
          </div>
        </div>
      )}
      {tab === '成员' && (
        <div className="space-y-5">
          <div className={`card flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between ${currentRoleInfo ? roleTone[currentRoleInfo.id] : ''}`}>
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white text-indigo-600 shadow-sm ring-1 ring-slate-200"><ShieldCheck size={20} /></span>
              <div>
                <div className="flex items-center gap-2"><span className="text-[14px] font-semibold text-slate-900">你的角色</span><RoleBadge role={role} roles={roles} /></div>
                <div className="mt-1 text-[11px] text-slate-500">{currentRoleInfo?.description || '加载角色权限中…'}</div>
              </div>
            </div>
            <span className="badge bg-white text-slate-600 ring-1 ring-slate-200">{permissions.length} 项权限</span>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <div className="card h-fit space-y-3 p-5">
              <div className="flex items-center gap-2 section-title"><Users size={16} className="text-indigo-500" /> 邀请成员</div>
              {allowed('member.invite') ? (
                <>
                  <div className="section-desc">被邀请成员会收到邮件，接受后加入当前工作空间。</div>
                  <Field label="成员邮箱"><input className="input" placeholder="name@company.com" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field>
                  <Field label="角色">
                    <select className="input" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
                      {inviteRoleOptions.map((item) => <option key={item} value={item}>{roleName(item, roles)}</option>)}
                    </select>
                  </Field>
                  <Button disabled={!invite.email} onClick={async () => {
                    setError('')
                    try { await tenantApi.invite(invite.email, invite.role); setMessage('邀请已发送'); setInvite({ email: '', role: inviteRoleOptions[0] }) }
                    catch (err) { setError(err instanceof Error ? err.message : '邀请失败') }
                  }}>发送邀请</Button>
                  <p className="text-xs leading-relaxed text-slate-500">所有者可邀请管理员；管理员可邀请编辑者、运行者和查看者。</p>
                </>
              ) : (
                <Callout tone="info">当前角色没有邀请成员权限。请联系管理员或所有者。</Callout>
              )}
            </div>

            <div className="space-y-3 xl:col-span-2">
              {members.map((member) => {
                const isSelf = member.user_id === user?.id
                const editable = canEditMember(member)
                const removable = canRemoveMember(member)
                const draftRole = memberRoles[member.user_id] || member.role
                const changed = draftRole !== member.role
                const roleOptions = role === 'owner' ? ['admin', 'editor', 'runner', 'viewer'] : ['editor', 'runner', 'viewer']
                return (
                  <div key={member.user_id} className="card p-4">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-slate-500 to-slate-700 text-[12px] font-bold text-white">{(member.name || member.email || '?').slice(0, 1).toUpperCase()}</span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2"><span className="truncate text-[13px] font-semibold text-slate-800">{member.name || member.email}</span>{isSelf && <span className="badge bg-indigo-50 text-indigo-700">你</span>}<RoleBadge role={member.role} roles={roles} /></div>
                          <div className="truncate text-[11px] text-slate-400">{member.email}</div>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {editable ? (
                          <select className="h-9 w-32 rounded-xl border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-slate-600 outline-none focus:border-indigo-400" value={draftRole} onChange={(event) => setMemberRoles({ ...memberRoles, [member.user_id]: event.target.value })}>
                            {roleOptions.map((item) => <option key={item} value={item}>{roleName(item, roles)}</option>)}
                          </select>
                        ) : (
                          <Lock size={14} className="text-slate-300" />
                        )}
                        {editable && changed && <Button className="h-9 px-3 text-[11px]" onClick={() => void saveMemberRole(member)}>保存</Button>}
                        {removable && <Button variant="ghost" className="h-9 px-2 text-rose-600" onClick={() => void removeMember(member)}><Trash2 size={14} /></Button>}
                      </div>
                    </div>
                    {member.role === 'owner' && <div className="mt-2 text-[10px] text-slate-400">所有者角色不可在这里修改或移除。</div>}
                    {!editable && member.role === 'admin' && role !== 'owner' && <div className="mt-2 text-[10px] text-slate-400">只有所有者可以修改管理员角色。</div>}
                  </div>
                )
              })}
              {!members.length && <div className="card p-10 text-center text-sm text-slate-500">暂无成员。</div>}
            </div>
          </div>
        </div>
      )}

      {tab === '权限' && (
        <div className="space-y-4">
          <Callout tone="info" title="Dify 风格工作空间角色">
            权限按工作空间生效。所有者拥有全部权限；管理员管理资源、成员和凭据；编辑者负责创建与发布；运行者执行流程；查看者只读。
          </Callout>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {roles.map((item) => {
              const current = item.id === role
              return (
                <div key={item.id} className={`card p-5 ${roleTone[item.id] || ''} ${current ? 'ring-2 ring-indigo-200' : ''}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2"><span className="grid h-9 w-9 place-items-center rounded-xl bg-white text-indigo-600 shadow-sm ring-1 ring-slate-200"><UserCog size={17} /></span><div><div className="text-[14px] font-semibold text-slate-900">{item.name}</div><div className="text-[10px] text-slate-400">{item.id}</div></div></div>
                    {current && <span className="badge bg-white text-indigo-700 ring-1 ring-indigo-200">当前角色</span>}
                  </div>
                  <p className="mt-3 min-h-[48px] text-[11px] leading-relaxed text-slate-500">{item.description}</p>
                  <div className="mt-2 space-y-1">
                    {item.highlights.map((highlight) => <div key={highlight} className="flex items-start gap-1.5 text-[10px] text-slate-500"><span className="mt-1 h-1 w-1 rounded-full bg-indigo-400" />{highlight}</div>)}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {item.permissions.slice(0, 12).map((permission) => <span key={permission} className="badge bg-white text-slate-500 ring-1 ring-slate-200">{permissionLabels[permission] || permission}</span>)}
                    {item.permissions.length > 12 && <span className="badge bg-white text-slate-400 ring-1 ring-slate-200">+{item.permissions.length - 12}</span>}
                  </div>
                </div>
              )
            })}
          </div>
          {!roles.length && <div className="card p-10 text-center text-sm text-slate-500">角色权限加载中…</div>}
        </div>
      )}
      {tab === '审计' && (
        <div className="table-shell">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-100 bg-slate-50/80 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400"><tr><th className="px-5 py-3">动作</th><th className="px-5 py-3">资源</th><th className="px-5 py-3">时间</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {audit.map((item) => (
                <tr key={item.id}><td className="px-5 py-3 font-mono text-xs">{item.action}</td><td className="px-5 py-3">{item.resource_type} {item.resource_id?.slice(0, 8)}</td><td className="px-5 py-3 text-slate-500">{new Date(item.created_at).toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
          {!audit.length && <div className="p-10 text-center text-sm text-slate-500">暂无审计记录。</div>}
        </div>
      )}
    </div>
  )
}
