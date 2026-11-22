from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def is_expired(value: datetime) -> bool:
    return ensure_aware(value) < utcnow()


def new_id() -> str:
    return str(uuid.uuid4())


class EmbeddingType(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(1024))
            except Exception:
                return dialect.type_descriptor(JSON())
        return dialect.type_descriptor(JSON())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_membership"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    draft_dsl: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_version_id: Mapped[str | None] = mapped_column(String(36))
    version_no: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    dsl: Mapped[dict[str, Any]] = mapped_column(JSON)
    dsl_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflows.id"), index=True)
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_versions.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    trigger_type: Mapped[str] = mapped_column(String(30), default="manual")
    trigger_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NodeRun(Base):
    __tablename__ = "node_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    node_id: Mapped[str] = mapped_column(String(120), index=True)
    node_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    node_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    node_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    assignee_role: Mapped[str] = mapped_column(String(20), default="editor")
    decided_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflows.id"), index=True)
    cron: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflows.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    hmac_secret: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelProfile(Base, TimestampMixin):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(30), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(200))
    api_key_secret: Mapped[str] = mapped_column(String(120), default="")
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=1024)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=120)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Secret(Base):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tenant_secret"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Tool(Base, TimestampMixin):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(30), default="http")
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class McpServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    transport: Mapped[str] = mapped_column(String(40), default="streamable_http")
    url: Mapped[str] = mapped_column(String(500))
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpTool(Base):
    __tablename__ = "mcp_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    server_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentProfile(Base, TimestampMixin):
    __tablename__ = "agent_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    role_prompt: Mapped[str] = mapped_column(Text)
    model_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    kb_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_iterations: Mapped[int] = mapped_column(Integer, default=8)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    temperature: Mapped[float] = mapped_column(Float, default=0.2)


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    embedding_model_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chunk_size: Mapped[int] = mapped_column(Integer, default=800)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=100)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class KbMember(Base):
    __tablename__ = "kb_members"
    __table_args__ = (UniqueConstraint("kb_id", "user_id", name="uq_kb_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    kb_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    kb_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_profiles.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    tokens: Mapped[int] = mapped_column(Integer, default=0)


class OAuthConnection(Base, TimestampMixin):
    __tablename__ = "oauth_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    auth_url: Mapped[str] = mapped_column(String(1000))
    token_url: Mapped[str] = mapped_column(String(1000))
    client_id: Mapped[str] = mapped_column(String(500))
    client_secret_ciphertext: Mapped[str] = mapped_column(Text)
    token_auth_method: Mapped[str] = mapped_column(String(30), default="client_secret_post")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, default="")
    refresh_token_ciphertext: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class PluginInstallation(Base, TimestampMixin):
    __tablename__ = "plugin_installations"
    __table_args__ = (UniqueConstraint("tenant_id", "plugin_id", name="uq_plugin_installation"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    plugin_id: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(30), default="1.0.0")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="installed")
    tool_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    installed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    kb_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType, nullable=True)
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(120), index=True)
    mode: Mapped[str] = mapped_column(String(30), default="single")
    status: Mapped[str] = mapped_column(String(30), default="running")
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_budget: Mapped[int] = mapped_column(Integer, default=100000)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(30))
    agent_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("tenant_id", "day", name="uq_usage_day"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    day: Mapped[date] = mapped_column(Date)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0)
    runner_seconds: Mapped[int] = mapped_column(Integer, default=0)
    storage_bytes: Mapped[int] = mapped_column(Integer, default=0)


