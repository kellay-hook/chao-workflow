export type User = { id: string; email: string; name: string; email_verified: boolean }
export type Tenant = { id: string; name: string; slug: string; settings: Record<string, unknown> }
export type Membership = {
  tenant_id: string
  user_id: string
  role: string
  email: string | null
  name: string | null
}

export type RoleInfo = {
  id: string
  role: string
  name: string
  description: string
  color: string
  highlights: string[]
  permissions: string[]
}

export type PermissionSummary = {
  role: string
  role_name: string
  permissions: string[]
  roles: RoleInfo[]
  can_manage_members: boolean
  invitable_roles: string[]
}

export type AuthResponse = {
  access_token: string
  token_type: string
  expires_in: number
  user: User
  tenants: Tenant[]
  active_tenant: Tenant | null
  verification_token?: string | null
}

export type NodeType =
  | 'start'
  | 'end'
  | 'llm'
  | 'agent'
  | 'agent_team'
  | 'tool'
  | 'http'
  | 'condition'
  | 'loop'
  | 'code'
  | 'approval'
  | 'subworkflow'

export type WorkflowNode = {
  id: string
  type: NodeType
  name?: string
  config: Record<string, any>
  position: { x: number; y: number }
}

export type WorkflowEdge = {
  id: string
  source: string
  target: string
  source_port?: string
  target_port?: string
}

export type WorkflowDSL = {
  schema_version: '1.0'
  inputs: Record<string, any>
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  settings: { timeout_sec: number; max_parallel: number; on_error: 'fail' | 'continue' }
}

export type Workflow = {
  id: string
  tenant_id: string
  name: string
  description: string
  draft_dsl: WorkflowDSL
  current_version_id: string | null
  version_no: number
  created_at: string
  updated_at: string
}

export type WorkflowTemplate = {
  id: string
  name: string
  description: string
  category: string
  trigger: string
  icon: string
  highlights: string[]
  node_count: number
  input_count: number
  preview_nodes: { type: string; name: string }[]
}

export type WebhookEndpoint = {
  id: string
  name: string
  enabled: boolean
  url: string
  require_signature?: boolean
  created_at?: string
}

export type McpServer = {
  id: string
  tenant_id: string
  name: string
  transport: string
  url: string
  enabled: boolean
  last_discovered_at: string | null
}

export type McpTool = {
  id: string
  server_id: string
  name: string
  description: string
  input_schema: Record<string, any>
  risk_level: string
  enabled: boolean
}

export type WorkflowVersion = {
  id: string
  workflow_id: string
  version: number
  dsl_hash: string
  dsl: WorkflowDSL
  published_at: string
}

export type Run = {
  id: string
  tenant_id: string
  workflow_id: string
  version_id: string
  status: string
  trigger_type: string
  inputs: Record<string, any>
  output: Record<string, any> | null
  error: Record<string, any> | null
  token_usage: number
  cost_usd: number
  parent_run_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export type NodeRun = {
  id: string
  run_id: string
  node_id: string
  node_type: string
  status: string
  attempt: number
  input: Record<string, any> | null
  output: Record<string, any> | null
  error: Record<string, any> | null
  tokens: number
  started_at: string | null
  finished_at: string | null
}

export type Approval = {
  id: string
  tenant_id: string
  run_id: string
  node_id: string | null
  agent_name: string | null
  tool_name: string | null
  title: string
  description: string
  args: Record<string, any>
  risk_level: string
  status: string
  assignee_role: string
  expires_at: string
  created_at: string
}

export type Tool = {
  id: string
  tenant_id: string
  name: string
  type: string
  description: string
  input_schema: Record<string, any>
  config: Record<string, any>
  risk_level: string
  enabled: boolean
}

export type AgentProfile = {
  id: string
  tenant_id: string
  name: string
  role_prompt: string
  model_profile_id: string | null
  tool_ids: string[]
  kb_ids: string[]
  max_iterations: number
  output_schema: Record<string, any>
  temperature: number
}

export type ModelProfile = {
  id: string
  tenant_id: string
  name: string
  provider: string
  base_url: string
  model: string
  has_api_key: boolean
  embedding_dimension: number
  max_tokens: number
  temperature: number
  timeout_sec: number
  is_default: boolean
}

export type KnowledgeBase = {
  id: string
  tenant_id: string
  name: string
  description: string
  embedding_model_profile_id: string | null
  chunk_size: number
  chunk_overlap: number
  created_at: string
}

export type DocumentItem = {
  id: string
  tenant_id: string
  kb_id: string
  filename: string
  mime_type: string
  size: number
  status: string
  error: string
  version: number
  metadata_json: Record<string, any>
  created_at: string
}

export type SearchHit = {
  chunk_id: string
  document_id: string
  title: string
  text: string
  score: number
  metadata: Record<string, any>
  citation: Record<string, any>
}

export type SearchResponse = { hits: SearchHit[]; query: string; rerank_mode?: string; rerank_error?: string | null }
export type KbStats = { documents: number; ready: number; processing: number; failed: number; chunks: number }
export type Chunk = { id: string; document_id: string; chunk_index: number; text: string; token_count: number; metadata_json: Record<string, any> }
export type AgentTestResponse = { output: any; content: string; tokens: number; requires_approval: boolean; approval: Record<string, any> | null; messages: Record<string, any>[]; session_id?: string | null }
export type AgentSession = { id: string; tenant_id: string; agent_profile_id: string; user_id: string | null; title: string; messages: Record<string, any>[]; tokens: number; created_at: string; updated_at: string }
export type AgentSessionSummary = Omit<AgentSession, 'messages'> & { message_count: number }
export type OAuthConnection = { id: string; tenant_id: string; name: string; auth_url: string; token_url: string; client_id: string; token_auth_method: string; scopes: string[]; status: string; expires_at: string | null; created_at: string }
export type PluginConfigField = {
  key: string
  label: string
  type?: 'text' | 'url' | 'password' | 'select' | 'number'
  required?: boolean
  placeholder?: string
  hint?: string
  default?: string | number
  options?: string[]
}

export type PluginDefinition = {
  id: string
  name: string
  description: string
  category: string
  vendor: string
  version: string
  icon: string
  permissions: string[]
  risk_level: string
  input_schema: Record<string, any>
  config_schema: PluginConfigField[]
  highlights: string[]
  installed: boolean
}

export type InstalledPlugin = PluginDefinition & {
  installation_id: string
  config: Record<string, any>
  tool_id: string | null
  installed_at: string
}

export type Usage = { runs: number; llm_tokens: number; embedding_tokens: number; runner_seconds: number; storage_bytes: number }
export type ValidationResult = { valid: boolean; issues: { code: string; message: string; node_id?: string }[] }
