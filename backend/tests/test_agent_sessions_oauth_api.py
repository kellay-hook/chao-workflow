from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.api import agent_sessions, oauth
from app.db import Base, get_session
from app.deps import Principal, require_tenant
from app.models import AgentProfile, OAuthConnection, utcnow
from app.services.agent_runtime import AgentResult


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        session.add_all(
            [
                AgentProfile(id="agent-1", tenant_id="tenant-1", name="Researcher", role_prompt="help"),
                AgentProfile(id="agent-2", tenant_id="tenant-2", name="Other", role_prompt="other"),
            ]
        )
        await session.commit()

    principal = Principal(user_id="user-1", tenant_id="tenant-1", role="owner", scopes=["*"], auth_type="jwt")

    async def override_session():
        async with Session() as session:
            yield session

    async def override_principal() -> Principal:
        return principal

    app = FastAPI()
    app.include_router(agent_sessions.router)
    app.include_router(oauth.router)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_tenant] = override_principal

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, Session


@pytest.mark.asyncio
async def test_agent_session_crud_and_tenant_isolation(api):
    client, _Session = api
    created = await client.post(
        "/api/v1/tenants/tenant-1/agent-sessions",
        json={"agent_profile_id": "agent-1", "title": "Demo chat"},
    )
    assert created.status_code == 201, created.text
    session = created.json()
    assert session["title"] == "Demo chat"
    assert session["messages"] == []
    assert session["tokens"] == 0

    listed = await client.get("/api/v1/tenants/tenant-1/agent-sessions", params={"agent_profile_id": "agent-1"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [session["id"]]
    assert listed.json()[0]["message_count"] == 0
    assert "messages" not in listed.json()[0]

    detail = await client.get(f"/api/v1/tenants/tenant-1/agent-sessions/{session['id']}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    renamed = await client.patch(
        f"/api/v1/tenants/tenant-1/agent-sessions/{session['id']}",
        json={"title": "Renamed chat"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Renamed chat"

    foreign = await client.post(
        "/api/v1/tenants/tenant-1/agent-sessions",
        json={"agent_profile_id": "agent-2", "title": "Nope"},
    )
    assert foreign.status_code == 404

    deleted = await client.delete(f"/api/v1/tenants/tenant-1/agent-sessions/{session['id']}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/tenants/tenant-1/agent-sessions/{session['id']}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_agent_session_message_persistence(api, monkeypatch):
    client, _Session = api
    created = await client.post(
        "/api/v1/tenants/tenant-1/agent-sessions",
        json={"agent_profile_id": "agent-1", "title": "New conversation"},
    )
    session_id = created.json()["id"]
    captured = {}

    async def fake_run(session, **kwargs):
        goal = kwargs["goal"]
        history = list((kwargs.get("state") or {}).get("messages") or [])
        captured.setdefault("histories", []).append(history)
        messages = history or [
            {"role": "system", "content": "system"},
            {"role": "user", "content": goal},
        ]
        messages = messages + [{"role": "assistant", "content": f"answer to {goal}"}]
        return AgentResult(
            output={"answer": f"answer to {goal}"},
            content=f"answer to {goal}",
            tokens=12,
            state={"messages": messages, "tokens": 12},
        )

    monkeypatch.setattr(agent_sessions.agent_runtime, "run_agent", fake_run)
    first = await client.post(
        f"/api/v1/tenants/tenant-1/agent-sessions/{session_id}/messages",
        json={"goal": "hello", "inputs": {}},
    )
    assert first.status_code == 200, first.text
    assert first.json()["session_id"] == session_id
    assert first.json()["tokens"] == 12

    second = await client.post(
        f"/api/v1/tenants/tenant-1/agent-sessions/{session_id}/messages",
        json={"goal": "again", "inputs": {}},
    )
    assert second.status_code == 200, second.text
    # 第二次调用必须带上第一次的完整历史
    assert captured["histories"][1][0] == {"role": "system", "content": "system"}
    assert any(m.get("content") == "hello" for m in captured["histories"][1])

    detail = await client.get(f"/api/v1/tenants/tenant-1/agent-sessions/{session_id}")
    data = detail.json()
    assert data["title"] == "hello"
    assert data["tokens"] == 24
    assert any(m.get("content") == "answer to hello" for m in data["messages"])
    assert any(m.get("content") == "answer to again" for m in data["messages"])

    summary = await client.get(
        "/api/v1/tenants/tenant-1/agent-sessions", params={"agent_profile_id": "agent-1"}
    )
    assert summary.json()[0]["message_count"] == len(data["messages"])


@pytest.mark.asyncio
async def test_oauth_authorize_url_and_error_callback(api, monkeypatch):
    client, Session = api
    created = await client.post(
        "/api/v1/tenants/tenant-1/oauth-connections",
        json={
            "name": "Mock",
            "auth_url": "https://idp.example.com/authorize?audience=crm",
            "token_url": "https://idp.example.com/token",
            "client_id": "client-1",
            "client_secret": "secret-1",
            "scopes": ["read", "write"],
        },
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    assert "client_secret" not in connection

    authorize = await client.get(f"/api/v1/tenants/tenant-1/oauth-connections/{connection['id']}/authorize-url")
    assert authorize.status_code == 200
    url = authorize.json()["authorize_url"]
    query = parse_qs(urlparse(url).query)
    assert query["client_id"] == ["client-1"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["read write"]
    assert query["redirect_uri"] == ["http://localhost:8020/api/v1/oauth/callback"]
    assert query["audience"] == ["crm"]
    assert query["state"][0]

    error = await client.get(
        "/api/v1/oauth/callback",
        params={"error": "access_denied", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert error.status_code in {302, 307}
    assert "oauth=error" in error.headers["location"]

    invalid = await client.get(
        "/api/v1/oauth/callback",
        params={"code": "abc", "state": "not-a-state"},
        follow_redirects=False,
    )
    assert invalid.status_code in {302, 307}
    assert "oauth=error" in invalid.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_marks_connection_connected(api, monkeypatch):
    client, Session = api
    created = await client.post(
        "/api/v1/tenants/tenant-1/oauth-connections",
        json={
            "name": "Mock",
            "auth_url": "https://idp.example.com/authorize",
            "token_url": "https://idp.example.com/token",
            "client_id": "client-1",
            "client_secret": "secret-1",
        },
    )
    connection = created.json()
    authorize = await client.get(f"/api/v1/tenants/tenant-1/oauth-connections/{connection['id']}/authorize-url")
    state = parse_qs(urlparse(authorize.json()["authorize_url"]).query)["state"][0]

    async def fake_exchange(item: OAuthConnection, code: str) -> None:
        assert code == "code-1"
        item.status = "connected"
        item.expires_at = utcnow() + timedelta(hours=1)

    monkeypatch.setattr(oauth.oauth, "exchange_code", fake_exchange)
    callback = await client.get(
        "/api/v1/oauth/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code in {302, 307}
    assert "oauth=success" in callback.headers["location"]

    disconnected = await client.post(
        f"/api/v1/tenants/tenant-1/oauth-connections/{connection['id']}/disconnect"
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["status"] == "disconnected"

    async with Session() as session:
        item = (
            await session.execute(select(OAuthConnection).where(OAuthConnection.id == connection["id"]))
        ).scalar_one()
        assert item.status == "disconnected"
        assert item.access_token_ciphertext == ""
        assert item.refresh_token_ciphertext == ""
