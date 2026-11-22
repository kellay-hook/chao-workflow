from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.api import plugins as plugins_api
from app.db import Base, get_session
from app.deps import Principal, require_tenant
from app.models import PluginInstallation, Tool
from app.services import plugins
from app.services.tools import ToolInfo, execute_registered_tool


def test_safe_calculator():
    assert plugins.safe_calculate("(12 + 3) * 4") == 60
    assert plugins.safe_calculate("2 ** 8") == 256
    with pytest.raises(ValueError):
        plugins.safe_calculate("__import__('os').system('whoami')")


def test_text_stats_and_json_extract():
    import asyncio

    stats = asyncio.run(plugins.execute_plugin("text_stats", {}, {"text": "hello world\nhello"}))
    assert stats["characters"] > 0
    assert stats["words"] == 3
    assert stats["lines"] == 2
    extracted = asyncio.run(
        plugins.execute_plugin(
            "json_extract",
            {},
            {"data": {"items": [{"name": "alpha"}]}, "expression": "items[0].name"},
        )
    )
    assert extracted["result"] == "alpha"


def test_required_plugin_config():
    definition = plugins.get_plugin("webhook_notify")
    assert definition is not None
    with pytest.raises(ValueError):
        plugins.validate_config(definition, {})
    assert plugins.validate_config(definition, {"webhook_url": "https://example.com/hook"})["webhook_url"] == "https://example.com/hook"


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'plugins.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    principal = Principal(user_id="user-1", tenant_id="tenant-1", role="owner", scopes=["*"], auth_type="jwt")

    async def override_session():
        async with Session() as session:
            yield session

    async def override_principal() -> Principal:
        return principal

    app = FastAPI()
    app.include_router(plugins_api.router)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_tenant] = override_principal

    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, Session


@pytest.mark.asyncio
async def test_plugin_install_test_and_uninstall(api):
    client, Session = api
    catalog = await client.get("/api/v1/tenants/tenant-1/plugins/catalog")
    assert catalog.status_code == 200
    items = catalog.json()
    assert any(item["id"] == "calculator" for item in items)
    assert all(item["installed"] is False for item in items)

    installed = await client.post(
        "/api/v1/tenants/tenant-1/plugins/calculator/install",
        json={"config": {}},
    )
    assert installed.status_code == 201, installed.text
    data = installed.json()
    assert data["installed"] is True
    assert data["tool_id"]

    duplicate = await client.post(
        "/api/v1/tenants/tenant-1/plugins/calculator/install",
        json={"config": {}},
    )
    assert duplicate.status_code == 409

    listing = await client.get("/api/v1/tenants/tenant-1/plugins")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == ["calculator"]

    tested = await client.post(
        "/api/v1/tenants/tenant-1/plugins/calculator/test",
        json={"inputs": {"expression": "(12 + 3) * 4"}},
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["result"]["result"] == 60

    async with Session() as session:
        tool = (await session.execute(select(Tool).where(Tool.id == data["tool_id"]))).scalar_one()
        assert tool.type == "plugin"
        assert tool.config["plugin_id"] == "calculator"
        info = ToolInfo(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            risk_level=tool.risk_level,
            type=tool.type,
            config=tool.config,
        )
        tool_result = await execute_registered_tool(
            session, tenant_id="tenant-1", tool=info, inputs={"expression": "6 * 7"}
        )
        assert tool_result["result"] == 42

    removed = await client.delete("/api/v1/tenants/tenant-1/plugins/calculator")
    assert removed.status_code == 204
    async with Session() as session:
        assert (await session.execute(select(PluginInstallation))).scalars().all() == []
        assert (await session.execute(select(Tool))).scalars().all() == []


@pytest.mark.asyncio
async def test_plugin_install_validates_config(api):
    client, _Session = api
    response = await client.post(
        "/api/v1/tenants/tenant-1/plugins/webhook_notify/install",
        json={"config": {}},
    )
    assert response.status_code == 422
    assert "Webhook URL" in response.text