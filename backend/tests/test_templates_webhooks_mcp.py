from __future__ import annotations

from copy import deepcopy

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.api import mcp_demo, workflows
from app.db import Base, get_session
from app.deps import Principal, require_tenant
from app.models import ModelProfile, WebhookEndpoint, Workflow, WorkflowRun, WorkflowVersion
from app.schemas import validate_dsl
from app.services import workflow_templates


def test_all_templates_validate_with_model():
    for template in workflow_templates.WORKFLOW_TEMPLATES:
        dsl = deepcopy(template.dsl)
        for node in dsl.get("nodes", []):
            if node.get("type") == "llm":
                node.setdefault("config", {})["model_profile_id"] = "model-1"
        result = validate_dsl(dsl)
        assert result.valid, f"{template.id}: {result.issues}"


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'templates.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        session.add(
            ModelProfile(
                id="model-1",
                tenant_id="tenant-1",
                name="Default",
                provider="openai_compatible",
                base_url="https://api.example.com/v1",
                model="demo",
                embedding_dimension=1024,
                is_default=True,
            )
        )
        await session.commit()

    principal = Principal(user_id="user-1", tenant_id="tenant-1", role="owner", scopes=["*"], auth_type="jwt")

    async def override_session():
        async with Session() as session:
            yield session

    async def override_principal() -> Principal:
        return principal

    app = FastAPI()
    app.include_router(workflows.router)
    app.include_router(mcp_demo.router)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_tenant] = override_principal
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, Session


@pytest.mark.asyncio
async def test_create_workflow_from_template_fills_default_model(api):
    client, _Session = api
    templates = await client.get("/api/v1/tenants/tenant-1/workflows/templates")
    assert templates.status_code == 200
    assert len(templates.json()) >= 5
    response = await client.post(
        "/api/v1/tenants/tenant-1/workflows/templates/llm_summary",
        json={"name": "我的总结流程", "description": "自定义说明"},
    )
    assert response.status_code == 201, response.text
    workflow = response.json()
    assert workflow["name"] == "我的总结流程"
    assert workflow["description"] == "自定义说明"
    dsl = workflow["draft_dsl"]
    llm = next(node for node in dsl["nodes"] if node["type"] == "llm")
    assert llm["config"]["model_profile_id"] == "model-1"


@pytest.mark.asyncio
async def test_webhook_test_endpoint_creates_run(api, monkeypatch):
    client, Session = api
    dsl = {
        "schema_version": "1.0",
        "inputs": {"type": "object", "properties": {}},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "config": {}},
            {"id": "end", "type": "end", "name": "结束", "config": {"outputs": {"ok": True}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "end"}],
        "settings": {},
    }
    async with Session() as session:
        workflow = Workflow(tenant_id="tenant-1", name="Hook", description="", draft_dsl=dsl)
        session.add(workflow)
        await session.flush()
        version = WorkflowVersion(
            tenant_id="tenant-1",
            workflow_id=workflow.id,
            version=1,
            dsl=dsl,
            dsl_hash="hash",
        )
        session.add(version)
        await session.flush()
        workflow.current_version_id = version.id
        workflow.version_no = 1
        endpoint = WebhookEndpoint(
            tenant_id="tenant-1",
            workflow_id=workflow.id,
            name="Demo",
            token="wh_demo",
            hmac_secret="",
        )
        session.add(endpoint)
        await session.commit()
        workflow_id, webhook_id = workflow.id, endpoint.id

    dispatched = []
    monkeypatch.setattr(workflows, "dispatch_run", lambda run_id, tasks: dispatched.append(run_id))

    response = await client.post(
        f"/api/v1/tenants/tenant-1/workflows/{workflow_id}/webhooks/{webhook_id}/test",
        json={"event": "demo.created", "data": {"id": 1}},
    )
    assert response.status_code == 202, response.text
    assert response.json()["run_id"]
    assert dispatched == [response.json()["run_id"]]

    async with Session() as session:
        run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == response.json()["run_id"]))).scalar_one()
        assert run.trigger_type == "webhook"
        assert run.inputs["webhook"]["event"] == "demo.created"


@pytest.mark.asyncio
async def test_mcp_demo_server(api):
    client, _Session = api
    listing = await client.post(
        "/api/v1/mcp/demo",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert listing.status_code == 200
    names = [item["name"] for item in listing.json()["result"]["tools"]]
    assert names == ["echo", "add", "server_time"]

    called = await client.post(
        "/api/v1/mcp/demo",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 2, "b": 3}},
        },
    )
    assert called.status_code == 200
    assert called.json()["result"]["structuredContent"]["result"] == 5.0