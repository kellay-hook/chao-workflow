import type {
  AgentProfile,
  AgentSession,
  AgentSessionSummary,
  AgentTestResponse,
  Chunk,
  KbStats,
  OAuthConnection,
  Approval,
  AuthResponse,
  DocumentItem,
  KnowledgeBase,
  McpServer,
  McpTool,
  Membership,
  ModelProfile,
  PermissionSummary,
  PluginDefinition,
  InstalledPlugin,
  NodeRun,
  Run,
  SearchResponse,
  Tenant,
  Tool,
  Usage,
  ValidationResult,
  WebhookEndpoint,
  Workflow,
  WorkflowTemplate,
  WorkflowVersion,
} from './types'
import { getTenantId, getToken, setToken } from './session'

const BASE = '/api/v1'
let refreshPromise: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) return false
        const data = (await response.json()) as AuthResponse
        setToken(data.access_token)
        if (data.active_tenant) localStorage.setItem('flowmind_tenant', data.active_tenant.id)
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${BASE}${path}`, { ...init, headers, credentials: 'include' })
  if (response.status === 401 && retry && (await refreshSession())) {
    return request<T>(path, init, false)
  }
  if (!response.ok) {
    let detail: any = response.statusText
    try {
      const data = await response.json()
      detail = data.detail ?? data.error?.message ?? data
    } catch {
      /* ignore */
    }
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    throw new Error(message || `HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function tenantPath(path: string) {
  const tenantId = getTenantId()
  if (!tenantId) throw new Error('no active tenant')
  return `/tenants/${tenantId}${path}`
}

export const authApi = {
  register: (payload: { email: string; password: string; name?: string; tenant_name?: string }) =>
    request<AuthResponse>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  login: (payload: { email: string; password: string }) =>
    request<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),
  me: () => request<{ user: AuthResponse['user']; tenants: Tenant[]; active_tenant_id: string; role: string }>('/auth/me'),
  verify: (token: string) => request<{ ok: boolean }>('/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  switchTenant: (tenantId: string) =>
    request<AuthResponse>('/auth/switch-tenant?tenant_id=' + encodeURIComponent(tenantId), { method: 'POST' }),
  acceptInvite: (token: string, password: string, name = '') =>
    request<AuthResponse>('/auth/accept-invite', {
      method: 'POST',
      body: JSON.stringify({ token, password, name }),
    }),
}

export const tenantApi = {
  list: () => request<Tenant[]>('/tenants'),
  create: (name: string) => request<Tenant>('/tenants', { method: 'POST', body: JSON.stringify({ name }) }),
  usage: () => request<Usage>(tenantPath('/usage')),
  members: () => request<Membership[]>(tenantPath('/members')),
  updateMemberRole: (userId: string, role: string) =>
    request<{ ok: boolean }>(tenantPath(`/members/${userId}`), { method: 'PATCH', body: JSON.stringify({ role }) }),
  removeMember: (userId: string) => request<void>(tenantPath(`/members/${userId}`), { method: 'DELETE' }),
  permissions: () => request<PermissionSummary>(tenantPath('/permissions/me')),
  invite: (email: string, role: string) =>
    request<{ ok: boolean }>(tenantPath('/invitations'), { method: 'POST', body: JSON.stringify({ email, role }) }),
  audit: () => request<any[]>(tenantPath('/audit')),
}

export const workflowApi = {
  list: () => request<Workflow[]>(tenantPath('/workflows')),
  create: (payload: { name: string; description?: string; dsl?: Record<string, any> }) =>
    request<Workflow>(tenantPath('/workflows'), { method: 'POST', body: JSON.stringify(payload) }),
  get: (id: string) => request<Workflow>(tenantPath(`/workflows/${id}`)),
  update: (id: string, payload: Record<string, any>) =>
    request<Workflow>(tenantPath(`/workflows/${id}`), { method: 'PATCH', body: JSON.stringify(payload) }),
  remove: (id: string) => request<void>(tenantPath(`/workflows/${id}`), { method: 'DELETE' }),
  validate: (id: string) => request<ValidationResult>(tenantPath(`/workflows/${id}/validate`), { method: 'POST' }),
  publish: (id: string) => request<WorkflowVersion>(tenantPath(`/workflows/${id}/publish`), { method: 'POST' }),
  versions: (id: string) => request<WorkflowVersion[]>(tenantPath(`/workflows/${id}/versions`)),
  run: (id: string, inputs: Record<string, any>, idempotencyKey?: string) =>
    request<Run>(tenantPath(`/workflows/${id}/runs`), {
      method: 'POST',
      body: JSON.stringify({ inputs, idempotency_key: idempotencyKey }),
    }),
  schedules: (id: string) => request<any[]>(tenantPath(`/workflows/${id}/schedules`)),
  createSchedule: (id: string, cron: string) =>
    request<any>(tenantPath(`/workflows/${id}/schedules`), { method: 'POST', body: JSON.stringify({ cron }) }),
  webhooks: (id: string) => request<any[]>(tenantPath(`/workflows/${id}/webhooks`)),
  createWebhook: (id: string, name: string, requireSignature = true) =>
    request<any>(tenantPath(`/workflows/${id}/webhooks`), { method: 'POST', body: JSON.stringify({ name, require_signature: requireSignature }) }),
  testWebhook: (id: string, webhookId: string, payload: Record<string, any>) =>
    request<{ run_id: string; status: string; payload: Record<string, any> }>(tenantPath(`/workflows/${id}/webhooks/${webhookId}/test`), { method: 'POST', body: JSON.stringify(payload) }),
  deleteWebhook: (id: string, webhookId: string) =>
    request<void>(tenantPath(`/workflows/${id}/webhooks/${webhookId}`), { method: 'DELETE' }),
  templates: () => request<WorkflowTemplate[]>(tenantPath('/workflows/templates')),
  createFromTemplate: (templateId: string, payload: { name?: string; description?: string } = {}) =>
    request<Workflow>(tenantPath(`/workflows/templates/${templateId}`), { method: 'POST', body: JSON.stringify(payload) }),
}

export const runApi = {
  list: (params: { workflow_id?: string; run_status?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.workflow_id) query.set('workflow_id', params.workflow_id)
    if (params.run_status) query.set('run_status', params.run_status)
    return request<Run[]>(tenantPath(`/runs?${query.toString()}`))
  },
  get: (id: string) => request<Run>(tenantPath(`/runs/${id}`)),
  nodes: (id: string) => request<NodeRun[]>(tenantPath(`/runs/${id}/nodes`)),
  cancel: (id: string) => request<Run>(tenantPath(`/runs/${id}/cancel`), { method: 'POST' }),
  retry: (id: string) => request<Run>(tenantPath(`/runs/${id}/retry`), { method: 'POST' }),
}

export const approvalApi = {
  list: (status = 'pending') => request<Approval[]>(tenantPath(`/approvals?approval_status=${status}`)),
  approve: (id: string, comment = '') =>
    request<Approval>(tenantPath(`/approvals/${id}/approve`), { method: 'POST', body: JSON.stringify({ comment }) }),
  reject: (id: string, comment = '') =>
    request<Approval>(tenantPath(`/approvals/${id}/reject`), { method: 'POST', body: JSON.stringify({ comment }) }),
}

export const resourceApi = {
  tools: () => request<Tool[]>(tenantPath('/tools')),
  createTool: (payload: Record<string, any>) =>
    request<Tool>(tenantPath('/tools'), { method: 'POST', body: JSON.stringify(payload) }),
  updateTool: (id: string, payload: Record<string, any>) =>
    request<Tool>(tenantPath(`/tools/${id}`), { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteTool: (id: string) => request<void>(tenantPath(`/tools/${id}`), { method: 'DELETE' }),
  agents: () => request<AgentProfile[]>(tenantPath('/agent-profiles')),
  createAgent: (payload: Record<string, any>) =>
    request<AgentProfile>(tenantPath('/agent-profiles'), { method: 'POST', body: JSON.stringify(payload) }),
  updateAgent: (id: string, payload: Record<string, any>) =>
    request<AgentProfile>(tenantPath(`/agent-profiles/${id}`), { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteAgent: (id: string) =>
    request<void>(tenantPath(`/agent-profiles/${id}`), { method: 'DELETE' }),
  testAgent: (id: string, goal: string, inputs: Record<string, any> = {}, history: Record<string, any>[] = []) =>
    request<AgentTestResponse>(tenantPath(`/agent-profiles/${id}/test`), {
      method: 'POST',
      body: JSON.stringify({ goal, inputs, history }),
    }),
  agentSessions: (agentId?: string) =>
    request<AgentSessionSummary[]>(tenantPath(`/agent-sessions${agentId ? `?agent_profile_id=${encodeURIComponent(agentId)}` : ''}`)),
  agentSession: (id: string) => request<AgentSession>(tenantPath(`/agent-sessions/${id}`)),
  createAgentSession: (agentId: string, title = '新对话') =>
    request<AgentSession>(tenantPath('/agent-sessions'), { method: 'POST', body: JSON.stringify({ agent_profile_id: agentId, title }) }),
  renameAgentSession: (id: string, title: string) =>
    request<AgentSession>(tenantPath(`/agent-sessions/${id}`), { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteAgentSession: (id: string) => request<void>(tenantPath(`/agent-sessions/${id}`), { method: 'DELETE' }),
  sendAgentSessionMessage: (id: string, goal: string, inputs: Record<string, any> = {}) =>
    request<AgentTestResponse>(tenantPath(`/agent-sessions/${id}/messages`), { method: 'POST', body: JSON.stringify({ goal, inputs }) }),
  oauthConnections: () => request<OAuthConnection[]>(tenantPath('/oauth-connections')),
  createOAuthConnection: (payload: Record<string, any>) =>
    request<OAuthConnection>(tenantPath('/oauth-connections'), { method: 'POST', body: JSON.stringify(payload) }),
  mcpServers: () => request<McpServer[]>(tenantPath('/mcp-servers')),
  createMcpServer: (payload: Record<string, any>) =>
    request<McpServer>(tenantPath('/mcp-servers'), { method: 'POST', body: JSON.stringify(payload) }),
  discoverMcp: (serverId: string) =>
    request<McpTool[]>(tenantPath(`/mcp-servers/${serverId}/discover`), { method: 'POST' }),
  mcpServerTools: (serverId: string) =>
    request<McpTool[]>(tenantPath(`/mcp-servers/${serverId}/tools`)),
  addMcpTool: (serverId: string, toolId: string) =>
    request<Tool>(tenantPath(`/mcp-servers/${serverId}/tools/${toolId}/add`), { method: 'POST' }),
  deleteMcpServer: (serverId: string) => request<void>(tenantPath(`/mcp-servers/${serverId}`), { method: 'DELETE' }),
  testTool: (toolId: string, inputs: Record<string, any>) =>
    request<{ ok: boolean; result: any }>(tenantPath(`/tools/${toolId}/test`), { method: 'POST', body: JSON.stringify({ inputs }) }),
  deleteOAuthConnection: (id: string) => request<void>(tenantPath(`/oauth-connections/${id}`), { method: 'DELETE' }),
  oauthAuthorizeUrl: (id: string) => request<{ authorize_url: string }>(tenantPath(`/oauth-connections/${id}/authorize-url`)),
  disconnectOAuthConnection: (id: string) =>
    request<OAuthConnection>(tenantPath(`/oauth-connections/${id}/disconnect`), { method: 'POST' }),
  models: () => request<ModelProfile[]>(tenantPath('/model-profiles')),
  createModel: (payload: Record<string, any>) =>
    request<ModelProfile>(tenantPath('/model-profiles'), { method: 'POST', body: JSON.stringify(payload) }),
  updateModel: (id: string, payload: Record<string, any>) =>
    request<ModelProfile>(tenantPath(`/model-profiles/${id}`), { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteModel: (id: string) =>
    request<void>(tenantPath(`/model-profiles/${id}`), { method: 'DELETE' }),
  testModel: (id: string) => request<{ ok: boolean; content?: string; error?: string }>(tenantPath(`/model-profiles/${id}/test`), { method: 'POST' }),
  secrets: () => request<any[]>(tenantPath('/secrets')),
  createSecret: (name: string, value: string) =>
    request<any>(tenantPath('/secrets'), { method: 'POST', body: JSON.stringify({ name, value }) }),
  deleteSecret: (id: string) => request<void>(tenantPath(`/secrets/${id}`), { method: 'DELETE' }),
}

export const pluginApi = {
  catalog: () => request<PluginDefinition[]>(tenantPath('/plugins/catalog')),
  installed: () => request<InstalledPlugin[]>(tenantPath('/plugins')),
  install: (pluginId: string, config: Record<string, any> = {}) =>
    request<InstalledPlugin>(tenantPath(`/plugins/${pluginId}/install`), { method: 'POST', body: JSON.stringify({ config }) }),
  update: (pluginId: string, config: Record<string, any> = {}) =>
    request<InstalledPlugin>(tenantPath(`/plugins/${pluginId}`), { method: 'PATCH', body: JSON.stringify({ config }) }),
  remove: (pluginId: string) => request<void>(tenantPath(`/plugins/${pluginId}`), { method: 'DELETE' }),
  test: (pluginId: string, inputs: Record<string, any>) =>
    request<{ ok: boolean; result: any }>(tenantPath(`/plugins/${pluginId}/test`), { method: 'POST', body: JSON.stringify({ inputs }) }),
}

export const knowledgeApi = {
  list: () => request<KnowledgeBase[]>(tenantPath('/knowledge-bases')),
  create: (payload: Record<string, any>) =>
    request<KnowledgeBase>(tenantPath('/knowledge-bases'), { method: 'POST', body: JSON.stringify(payload) }),
  remove: (id: string) => request<void>(tenantPath(`/knowledge-bases/${id}`), { method: 'DELETE' }),
  update: (id: string, payload: Record<string, any>) =>
    request<KnowledgeBase>(tenantPath(`/knowledge-bases/${id}`), { method: 'PATCH', body: JSON.stringify(payload) }),
  stats: (id: string) => request<KbStats>(tenantPath(`/knowledge-bases/${id}/stats`)),
  chunks: (id: string, documentId: string) =>
    request<Chunk[]>(tenantPath(`/knowledge-bases/${id}/documents/${documentId}/chunks`)),
  reprocess: (id: string, documentId: string) =>
    request<DocumentItem>(tenantPath(`/knowledge-bases/${id}/documents/${documentId}/reprocess`), { method: 'POST' }),
  updateChunk: (id: string, chunkId: string, text: string) =>
    request<Chunk>(tenantPath(`/knowledge-bases/${id}/chunks/${chunkId}`), { method: 'PATCH', body: JSON.stringify({ text }) }),
  deleteChunk: (id: string, chunkId: string) =>
    request<void>(tenantPath(`/knowledge-bases/${id}/chunks/${chunkId}`), { method: 'DELETE' }),
  documents: (id: string) => request<DocumentItem[]>(tenantPath(`/knowledge-bases/${id}/documents`)),
  upload: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentItem>(tenantPath(`/knowledge-bases/${id}/documents/upload`), { method: 'POST', body: form })
  },
  removeDocument: (id: string, documentId: string) =>
    request<void>(tenantPath(`/knowledge-bases/${id}/documents/${documentId}`), { method: 'DELETE' }),
  search: (id: string, query: string, options: Record<string, any> = {}) =>
    request<SearchResponse>(tenantPath(`/knowledge-bases/${id}/search`), {
      method: 'POST',
      body: JSON.stringify({ query, top_k: 8, ...options }),
    }),
  updateDocument: (id: string, documentId: string, metadata_json: Record<string, any>) =>
    request<DocumentItem>(tenantPath(`/knowledge-bases/${id}/documents/${documentId}`), { method: 'PATCH', body: JSON.stringify({ metadata_json }) }),
}

export type StreamEvent = { event: string; data: any; id?: string }

export async function subscribeRun(runId: string, onEvent: (event: StreamEvent) => void) {
  const tenantId = getTenantId()
  if (!tenantId) return () => undefined
  const controller = new AbortController()
  const token = getToken()
  const response = await fetch(`${BASE}/tenants/${tenantId}/runs/${runId}/events`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: controller.signal,
    credentials: 'include',
  })
  if (!response.ok || !response.body) return () => controller.abort()
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consume = async () => {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() ?? ''
      for (const block of blocks) {
        const lines = block.split('\n')
        let event = 'message'
        let data = ''
        let id: string | undefined
        for (const line of lines) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
          else if (line.startsWith('id:')) id = line.slice(3).trim()
        }
        if (data) {
          try {
            onEvent({ event, data: JSON.parse(data), id })
          } catch {
            onEvent({ event, data, id })
          }
        }
      }
    }
  }
  consume().catch(() => undefined)
  return () => controller.abort()
}

