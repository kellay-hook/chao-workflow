from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.api import tenants, workflows
from app.db import Base, get_session
from app.deps import Principal, require_tenant
from app.models import Membership, Tenant, User
from app.permissions import has_permission, permission_for_route


def _principal(role: str, user_id: str = "user-owner") -> Principal:
    return Principal(user_id=user_id, tenant_id="tenant-1", role=role, scopes=["*"], auth_type="jwt")


def test_role_matrix():
    assert has_permission(_principal("viewer"), "workflow.read")
    assert not has_permission(_principal("viewer"), "workflow.create")
    assert has_permission(_principal("runner"), "workflow.run")
    assert not has_permission(_principal("runner"), "workflow.update")
    assert has_permission(_principal("editor"), "workflow.publish")
    assert has_permission(_principal("editor"), "knowledge.upload")
    assert not has_permission(_principal("editor"), "member.invite")
    assert not has_permission(_principal("editor"), "model.manage")
    assert has_permission(_principal("admin"), "member.invite")
    assert has_permission(_principal("admin"), "model.manage")
    assert has_permission(_principal("owner"), "workspace.transfer" if False else "settings.update")


def test_route_permissions():
    assert permission_for_route("GET", "/api/v1/tenants/t/workflows/w") == "workflow.read"
    assert permission_for_route("POST", "/api/v1/tenants/t/workflows/w/publish") == "workflow.publish"
    assert permission_for_route("POST", "/api/v1/tenants/t/workflows/w/runs") == "workflow.run"
    assert permission_for_route("DELETE", "/api/v1/tenants/t/workflows/w") == "workflow.delete"
    assert permission_for_route("POST", "/api/v1/tenants/t/knowledge-bases/k/documents/upload") == "knowledge.upload"
    assert permission_for_route("POST", "/api/v1/tenants/t/tools/x/test") == "tool.test"
    assert permission_for_route("GET", "/api/v1/tenants/t/plugins/catalog") == "plugin.read"


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'permissions.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        session.add(Tenant(id="tenant-1", name="Tenant", slug="tenant-1"))
        users = [
            User(id="user-owner", email="owner@example.com", name="Owner", password_hash="x", email_verified=True),
            User(id="user-admin", email="admin@example.com", name="Admin", password_hash="x", email_verified=True),
            User(id="user-editor", email="editor@example.com", name="Editor", password_hash="x", email_verified=True),
        ]
        session.add_all(users)
        session.add_all(
            [
                Membership(id="m-owner", tenant_id="tenant-1", user_id="user-owner", role="owner"),
                Membership(id="m-admin", tenant_id="tenant-1", user_id="user-admin", role="admin"),
                Membership(id="m-editor", tenant_id="tenant-1", user_id="user-editor", role="editor"),
            ]
        )
        await session.commit()

    current = {"principal": _principal("owner")}

    async def override_session():
        async with Session() as session:
            yield session

    async def override_principal() -> Principal:
        return current["principal"]

    app = FastAPI()
    app.include_router(tenants.router)
    app.include_router(workflows.router)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_tenant] = override_principal
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, Session, current


@pytest.mark.asyncio
async def test_permission_summary_and_member_management(api):
    client, Session, current = api
    current["principal"] = _principal("editor", "user-editor")
    summary = await client.get("/api/v1/tenants/tenant-1/permissions/me")
    assert summary.status_code == 200
    data = summary.json()
    assert data["role"] == "editor"
    assert data["can_manage_members"] is False
    assert "workflow.publish" in data["permissions"]
    assert "member.invite" not in data["permissions"]
    assert len(data["roles"]) == 5

    denied = await client.get("/api/v1/tenants/tenant-1/audit")
    assert denied.status_code == 403

    current["principal"] = _principal("admin", "user-admin")
    denied_admin = await client.patch(
        "/api/v1/tenants/tenant-1/members/user-editor",
        json={"role": "admin"},
    )
    assert denied_admin.status_code == 403

    current["principal"] = _principal("owner")
    promoted = await client.patch(
        "/api/v1/tenants/tenant-1/members/user-editor",
        json={"role": "runner"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "runner"

    owner_change = await client.patch(
        "/api/v1/tenants/tenant-1/members/user-owner",
        json={"role": "editor"},
    )
    assert owner_change.status_code == 403

    removed = await client.delete("/api/v1/tenants/tenant-1/members/user-editor")
    assert removed.status_code == 204
    async with Session() as session:
        left = (await session.execute(select(Membership).where(Membership.user_id == "user-editor"))).scalar_one_or_none()
        assert left is None


@pytest.mark.asyncio
async def test_viewer_cannot_create_workflow(api):
    client, _Session, current = api
    current["principal"] = _principal("viewer", "user-editor")
    denied = await client.post("/api/v1/tenants/tenant-1/workflows", json={"name": "Nope"})
    assert denied.status_code == 403

    current["principal"] = _principal("editor", "user-editor")
    allowed = await client.post("/api/v1/tenants/tenant-1/workflows", json={"name": "Allowed"})
    assert allowed.status_code == 201, allowed.text