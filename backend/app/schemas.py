from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.config import settings

NodeType = Literal[
    "start",
    "end",
    "llm",
    "agent",
    "agent_team",
    "tool",
    "http",
    "condition",
    "loop",
    "code",
    "approval",
    "subworkflow",
]

RiskLevel = Literal["low", "medium", "high", "deny"]
RunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "succeeded",
    "failed",
    "canceled",
    "timed_out",
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------- Auth / tenants ----------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)
    tenant_name: str = Field(default="", max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: str
    email: str
    name: str
    email_verified: bool


class TenantOut(ORMModel):
    id: str
    name: str
    slug: str
    settings: dict[str, Any] = Field(default_factory=dict)


class MembershipOut(BaseModel):
    tenant_id: str
    user_id: str
    role: str
    email: str | None = None
    name: str | None = None


class RoleInfo(BaseModel):
    id: str
    role: str
    name: str
    description: str
    color: str
    highlights: list[str]
    permissions: list[str]


class PermissionSummary(BaseModel):
    role: str
    role_name: str
    permissions: list[str]
    roles: list[RoleInfo]
    can_manage_members: bool
    invitable_roles: list[str]


class MemberRoleUpdate(BaseModel):
    role: Literal["admin", "editor", "runner", "viewer"]


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    tenants: list[TenantOut]
    active_tenant: TenantOut | None = None
    verification_token: str | None = None


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)


class InviteRequest(BaseModel):
    email: EmailStr
    role: Literal["admin", "editor", "runner", "viewer"] = "viewer"


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


# ---------- Workflow DSL ----------


class NodeModel(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    type: NodeType
    name: str = Field(default="", max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=dict)


class EdgeModel(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    source: str
    target: str
    source_port: str = "default"
    target_port: str = "default"


class WorkflowSettings(BaseModel):
    timeout_sec: int = Field(default=1800, ge=1, le=settings.max_run_seconds)
    max_parallel: int = Field(default=4, ge=1, le=16)
    on_error: Literal["fail", "continue"] = "fail"


class WorkflowDSL(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    inputs: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    nodes: list[NodeModel] = Field(default_factory=list)
    edges: list[EdgeModel] = Field(default_factory=list)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)

    @field_validator("nodes")
    @classmethod
    def limit_nodes(cls, value: list[NodeModel]) -> list[NodeModel]:
        if len(value) > settings.max_workflow_nodes:
            raise ValueError(f"workflow exceeds {settings.max_workflow_nodes} nodes")
        return value


class ValidationIssue(BaseModel):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    dsl: dict[str, Any] | None = None


REQUIRED_CONFIG: dict[str, tuple[str, ...]] = {
    "llm": ("model_profile_id",),
    "agent": ("agent_profile_id",),
    "agent_team": ("mode",),
    "tool": ("tool_id",),
    "http": ("method", "url"),
    "code": ("source",),
    "approval": ("title",),
    "subworkflow": ("workflow_version_id",),
    "loop": ("workflow_version_id", "items_expr"),
}


def _reachable(nodes: dict[str, NodeModel], edges: list[EdgeModel], start: str) -> set[str]:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        adjacency[edge.source].append(edge.target)
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for nxt in adjacency[current]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _has_cycle(nodes: dict[str, NodeModel], edges: list[EdgeModel]) -> bool:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in edges:
        adjacency[edge.source].append(edge.target)
        indegree[edge.target] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return visited != len(nodes)


def validate_dsl(raw: dict[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        dsl = WorkflowDSL.model_validate(raw)
    except Exception as exc:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(code="schema_error", message=str(exc))],
        )

    nodes = {node.id: node for node in dsl.nodes}
    if len(nodes) != len(dsl.nodes):
        issues.append(ValidationIssue(code="duplicate_node_id", message="node ids must be unique"))
    starts = [node for node in dsl.nodes if node.type == "start"]
    ends = [node for node in dsl.nodes if node.type == "end"]
    if len(starts) != 1:
        issues.append(
            ValidationIssue(code="start_count", message="workflow must have exactly one start node")
        )
    if not ends:
        issues.append(ValidationIssue(code="end_missing", message="workflow must have at least one end node"))
    if not starts:
        return ValidationResult(valid=False, issues=issues)

    start_id = starts[0].id
    for edge in dsl.edges:
        if edge.source not in nodes:
            issues.append(
                ValidationIssue(
                    code="edge_source_missing",
                    message=f"edge source {edge.source} does not exist",
                    edge_id=edge.id,
                )
            )
        if edge.target not in nodes:
            issues.append(
                ValidationIssue(
                    code="edge_target_missing",
                    message=f"edge target {edge.target} does not exist",
                    edge_id=edge.id,
                )
            )
        if edge.source == edge.target:
            issues.append(
                ValidationIssue(code="self_loop", message="self loops are not allowed", edge_id=edge.id)
            )

    known_edges = [e for e in dsl.edges if e.source in nodes and e.target in nodes]
    if _has_cycle(nodes, known_edges):
        issues.append(ValidationIssue(code="cycle", message="workflow graph must be acyclic"))

    reachable = _reachable(nodes, known_edges, start_id) if start_id in nodes else set()
    for node in dsl.nodes:
        if node.id not in reachable:
            issues.append(
                ValidationIssue(
                    code="unreachable_node",
                    message=f"node {node.name or node.id} is not reachable from start",
                    node_id=node.id,
                )
            )
        required = REQUIRED_CONFIG.get(node.type, ())
        for key in required:
            if not node.config.get(key):
                issues.append(
                    ValidationIssue(
                        code="missing_config",
                        message=f"{node.type} node requires config.{key}",
                        node_id=node.id,
                    )
                )
        if node.type in {"start", "end"}:
            continue
        if node.type == "condition":
            cases = node.config.get("cases")
            if not isinstance(cases, list) or not cases:
                issues.append(
                    ValidationIssue(
                        code="condition_cases",
                        message="condition node requires a non-empty cases list",
                        node_id=node.id,
                    )
                )
            else:
                case_ids = {str(case.get("id")) for case in cases if isinstance(case, dict)}
                outgoing = [e for e in known_edges if e.source == node.id]
                for edge in outgoing:
                    if edge.source_port not in case_ids and edge.source_port != "default":
                        issues.append(
                            ValidationIssue(
                                code="condition_port",
                                message=f"edge port {edge.source_port} does not match a case id",
                                node_id=node.id,
                                edge_id=edge.id,
                            )
                        )
        if node.type == "loop":
            try:
                max_iterations = int(node.config.get("max_iterations", 100))
            except (TypeError, ValueError):
                max_iterations = 101
            if max_iterations < 1 or max_iterations > 200:
                issues.append(
                    ValidationIssue(
                        code="loop_limit",
                        message="loop max_iterations must be between 1 and 200",
                        node_id=node.id,
                    )
                )
        if node.type == "code":
            language = node.config.get("language", "python")
            if language != "python":
                issues.append(
                    ValidationIssue(
                        code="code_language",
                        message="only Python code nodes are supported",
                        node_id=node.id,
                    )
                )
        if node.type == "agent_team":
            mode = node.config.get("mode")
            if mode not in {"supervisor", "graph"}:
                issues.append(
                    ValidationIssue(
                        code="agent_team_mode",
                        message="agent_team mode must be supervisor or graph",
                        node_id=node.id,
                    )
                )
            if mode == "graph" and not node.config.get("agents"):
                issues.append(
                    ValidationIssue(
                        code="agent_team_agents",
                        message="graph mode requires an agents list",
                        node_id=node.id,
                    )
                )

    start_node = nodes.get(start_id)
    if start_node and any(edge.target == start_id for edge in dsl.edges):
        issues.append(
            ValidationIssue(
                code="start_incoming",
                message="start node cannot have incoming edges",
                node_id=start_id,
            )
        )
    for end in ends:
        if any(edge.source == end.id for edge in dsl.edges):
            issues.append(
                ValidationIssue(
                    code="end_outgoing",
                    message="end node cannot have outgoing edges",
                    node_id=end.id,
                )
            )

    return ValidationResult(valid=not issues, issues=issues, dsl=dsl.model_dump())


# ---------- Workflow / runs ----------


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    dsl: dict[str, Any] | None = None


class WorkflowTemplateCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    dsl: dict[str, Any] | None = None
    version_no: int | None = None


class WorkflowOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    description: str
    draft_dsl: dict[str, Any]
    current_version_id: str | None
    version_no: int
    created_at: datetime
    updated_at: datetime


class WorkflowVersionOut(ORMModel):
    id: str
    workflow_id: str
    version: int
    dsl_hash: str
    dsl: dict[str, Any]
    published_at: datetime


class RunCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)


class RunOut(ORMModel):
    id: str
    tenant_id: str
    workflow_id: str
    version_id: str
    status: str
    trigger_type: str
    inputs: dict[str, Any]
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    token_usage: int
    cost_usd: float
    parent_run_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class NodeRunOut(ORMModel):
    id: str
    run_id: str
    node_id: str
    node_type: str
    status: str
    attempt: int
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    tokens: int
    started_at: datetime | None
    finished_at: datetime | None


class RunEventOut(ORMModel):
    id: int
    run_id: str
    type: str
    node_id: str | None
    data: dict[str, Any]
    created_at: datetime


class ApprovalOut(ORMModel):
    id: str
    tenant_id: str
    run_id: str
    node_id: str | None
    agent_name: str | None
    tool_name: str | None
    title: str
    description: str
    args: dict[str, Any]
    risk_level: str
    status: str
    assignee_role: str
    expires_at: datetime
    created_at: datetime


class ApprovalDecision(BaseModel):
    comment: str = ""


# ---------- Tools / models / agents / KB ----------


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["http", "mcp", "builtin", "subworkflow"] = "http"
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = "medium"
    enabled: bool = True


class ToolOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    type: str
    description: str
    input_schema: dict[str, Any]
    config: dict[str, Any]
    risk_level: str
    enabled: bool


class ToolTestRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class McpServerOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    transport: str
    url: str
    enabled: bool
    last_discovered_at: datetime | None


class McpToolOut(ORMModel):
    id: str
    server_id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: str
    enabled: bool


class ModelProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: Literal["openai_compatible", "ollama"] = "openai_compatible"
    base_url: str
    model: str
    api_key_secret: str = ""
    api_key: str = ""
    embedding_dimension: int = 1024
    max_tokens: int = 2048
    temperature: float = 0.2
    timeout_sec: int = 120
    is_default: bool = False


class ModelProfileOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    provider: str
    base_url: str
    model: str
    api_key_secret: str = Field(default="", exclude=True)
    embedding_dimension: int
    max_tokens: int
    temperature: float
    timeout_sec: int
    is_default: bool

    @computed_field
    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_secret)


class SecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    value: str = Field(min_length=1, max_length=8000)


class SecretOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    updated_at: datetime


class AgentProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role_prompt: str = Field(min_length=1)
    model_profile_id: str | None = None
    tool_ids: list[str] = Field(default_factory=list)
    kb_ids: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=8, ge=1, le=30)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.2


class AgentProfileOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    role_prompt: str
    model_profile_id: str | None
    tool_ids: list[str]
    kb_ids: list[str]
    max_iterations: int
    output_schema: dict[str, Any]
    temperature: float


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    embedding_model_profile_id: str | None = None
    chunk_size: int = Field(default=800, ge=200, le=2000)
    chunk_overlap: int = Field(default=100, ge=0, le=500)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    embedding_model_profile_id: str | None = None
    chunk_size: int | None = Field(default=None, ge=200, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)


class ChunkOut(ORMModel):
    id: str
    document_id: str
    chunk_index: int
    text: str
    token_count: int
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChunkUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class KbStatsOut(BaseModel):
    documents: int
    ready: int
    processing: int
    failed: int
    chunks: int


class AgentTestRequest(BaseModel):
    goal: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)


class AgentTestResponse(BaseModel):
    output: Any = None
    content: str = ""
    tokens: int = 0
    requires_approval: bool = False
    approval: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str | None = None


class KnowledgeBaseOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    description: str
    embedding_model_profile_id: str | None
    chunk_size: int
    chunk_overlap: int
    created_at: datetime


class DocumentOut(ORMModel):
    id: str
    tenant_id: str
    kb_id: str
    filename: str
    mime_type: str
    size: int
    status: str
    error: str
    version: int
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentUpdate(BaseModel):
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MetadataFilter(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    operator: Literal["eq", "ne", "contains", "in", "gte", "lte"] = "eq"
    value: Any = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=30)
    document_ids: list[str] = Field(default_factory=list)
    metadata_filters: list[MetadataFilter] = Field(default_factory=list)
    rerank_mode: Literal["none", "keyword", "llm"] = "none"
    rerank_model_profile_id: str | None = None


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    page: int | None = None
    sheet: str | None = None
    row_start: int | None = None
    row_end: int | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    citation: Citation


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    query: str
    rerank_mode: str = "none"
    rerank_error: str | None = None


class ApiKeyOut(ORMModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime


class AgentSessionCreate(BaseModel):
    agent_profile_id: str
    title: str = Field(default="New conversation", max_length=200)


class AgentSessionSummary(ORMModel):
    id: str
    tenant_id: str
    agent_profile_id: str
    user_id: str | None
    title: str
    tokens: int
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class AgentSessionOut(ORMModel):
    id: str
    tenant_id: str
    agent_profile_id: str
    user_id: str | None
    title: str
    messages: list[dict[str, Any]]
    tokens: int
    created_at: datetime
    updated_at: datetime


class AgentSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class AgentSessionMessageRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=20000)
    inputs: dict[str, Any] = Field(default_factory=dict)


class OAuthConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    auth_url: str
    token_url: str
    client_id: str
    client_secret: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    token_auth_method: Literal["client_secret_post", "client_secret_basic"] = "client_secret_post"


class OAuthConnectionOut(ORMModel):
    id: str
    tenant_id: str
    name: str
    auth_url: str
    token_url: str
    client_id: str
    token_auth_method: str
    scopes: list[str]
    status: str
    expires_at: datetime | None
    created_at: datetime


class OAuthAuthorizeOut(BaseModel):
    authorize_url: str


class PluginInstallRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class PluginTestRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class PluginCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    category: str
    vendor: str
    version: str
    icon: str
    permissions: list[str]
    risk_level: str
    input_schema: dict[str, Any]
    config_schema: list[dict[str, Any]]
    highlights: list[str]
    installed: bool = False


class InstalledPluginOut(PluginCatalogItem):
    installation_id: str
    config: dict[str, Any]
    tool_id: str | None
    installed_at: datetime


class UsageOut(BaseModel):
    runs: int
    llm_tokens: int
    embedding_tokens: int
    runner_seconds: int
    storage_bytes: int


class AuditOut(ORMModel):
    id: str
    tenant_id: str
    actor_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    detail: dict[str, Any]
    created_at: datetime


class Paginated(BaseModel):
    items: list[Any]
    next_cursor: str | None = None


def slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "workspace"
    return base[:60]


