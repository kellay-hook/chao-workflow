from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import Principal, audit_context, require_tenant
from app.models import PluginInstallation, Tool
from app.permissions import authorize_tenant_request
from app.schemas import (
    InstalledPluginOut,
    PluginCatalogItem,
    PluginInstallRequest,
    PluginTestRequest,
)
from app.services import plugins

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/plugins", tags=["plugins"], dependencies=[Depends(authorize_tenant_request)])


def _require_editor(principal: Principal) -> None:
    if principal.is_api_key or principal.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor required")


def _definition(plugin_id: str) -> plugins.PluginDefinition:
    definition = plugins.get_plugin(plugin_id)
    if not definition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found")
    return definition


def _catalog_item(definition: plugins.PluginDefinition, installed: bool = False) -> PluginCatalogItem:
    return PluginCatalogItem(**plugins.definition_dict(definition), installed=installed)


def _installed_out(definition: plugins.PluginDefinition, item: PluginInstallation) -> InstalledPluginOut:
    return InstalledPluginOut(
        **plugins.definition_dict(definition),
        installed=True,
        installation_id=item.id,
        config=dict(item.config or {}),
        tool_id=item.tool_id,
        installed_at=item.created_at,
    )


async def _installations(session: AsyncSession, tenant_id: str) -> list[PluginInstallation]:
    result = await session.execute(
        select(PluginInstallation)
        .where(PluginInstallation.tenant_id == tenant_id)
        .order_by(PluginInstallation.created_at.desc())
    )
    return list(result.scalars().all())


async def _installation(session: AsyncSession, tenant_id: str, plugin_id: str) -> PluginInstallation:
    result = await session.execute(
        select(PluginInstallation).where(
            PluginInstallation.tenant_id == tenant_id,
            PluginInstallation.plugin_id == plugin_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin is not installed")
    return item


@router.get("/catalog", response_model=list[PluginCatalogItem])
async def plugin_catalog(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[PluginCatalogItem]:
    installed = {item.plugin_id for item in await _installations(session, principal.tenant_id)}
    return [_catalog_item(definition, definition.id in installed) for definition in plugins.CATALOG]


@router.get("", response_model=list[InstalledPluginOut])
async def installed_plugins(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[InstalledPluginOut]:
    items = await _installations(session, principal.tenant_id)
    result = []
    for item in items:
        definition = plugins.get_plugin(item.plugin_id)
        if definition:
            result.append(_installed_out(definition, item))
    return result


@router.post("/{plugin_id}/install", response_model=InstalledPluginOut, status_code=status.HTTP_201_CREATED)
async def install_plugin(
    plugin_id: str,
    payload: PluginInstallRequest,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> InstalledPluginOut:
    _require_editor(principal)
    definition = _definition(plugin_id)
    try:
        config = plugins.validate_config(definition, payload.config)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    existing = await session.execute(
        select(PluginInstallation).where(
            PluginInstallation.tenant_id == principal.tenant_id,
            PluginInstallation.plugin_id == plugin_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="plugin already installed")

    tool = Tool(
        tenant_id=principal.tenant_id,
        name=definition.id,
        type="plugin",
        description=definition.description,
        input_schema=definition.input_schema,
        config={"plugin_id": definition.id, "plugin_config": config},
        risk_level=definition.risk_level,
        enabled=True,
    )
    session.add(tool)
    await session.flush()
    installation = PluginInstallation(
        tenant_id=principal.tenant_id,
        plugin_id=definition.id,
        version=definition.version,
        config=config,
        status="installed",
        tool_id=tool.id,
        installed_by=principal.user_id,
    )
    session.add(installation)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="plugin.install",
        resource_type="plugin",
        resource_id=installation.id,
        detail={"plugin_id": definition.id, "version": definition.version, "tool_id": tool.id},
        **audit_context(request),
    )
    await session.commit()
    return _installed_out(definition, installation)


@router.patch("/{plugin_id}", response_model=InstalledPluginOut)
async def update_plugin(
    plugin_id: str,
    payload: PluginInstallRequest,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> InstalledPluginOut:
    _require_editor(principal)
    definition = _definition(plugin_id)
    installation = await _installation(session, principal.tenant_id, plugin_id)
    try:
        config = plugins.validate_config(definition, payload.config)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    installation.config = config
    if installation.tool_id:
        tool = await session.get(Tool, installation.tool_id)
        if tool and tool.tenant_id == principal.tenant_id:
            tool.config = {"plugin_id": definition.id, "plugin_config": config}
    await session.commit()
    return _installed_out(definition, installation)


@router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_plugin(
    plugin_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    installation = await _installation(session, principal.tenant_id, plugin_id)
    if installation.tool_id:
        tool = await session.get(Tool, installation.tool_id)
        if tool and tool.tenant_id == principal.tenant_id:
            await session.delete(tool)
    await session.delete(installation)
    await session.commit()


@router.post("/{plugin_id}/test")
async def test_plugin(
    plugin_id: str,
    payload: PluginTestRequest,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_editor(principal)
    _definition(plugin_id)
    installation = await _installation(session, principal.tenant_id, plugin_id)
    try:
        result = await plugins.execute_plugin(plugin_id, dict(installation.config or {}), payload.inputs)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "result": result}