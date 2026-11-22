from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import Principal, audit_context, require_tenant
from app.models import (
    AgentProfile,
    McpServer,
    McpTool,
    ModelProfile,
    Secret,
    Tool,
    utcnow,
)
from app.permissions import authorize_tenant_request
from app.schemas import (
    AgentProfileCreate,
    AgentProfileOut,
    AgentTestRequest,
    AgentTestResponse,
    McpServerCreate,
    McpServerOut,
    McpToolOut,
    ModelProfileCreate,
    ModelProfileOut,
    SecretCreate,
    SecretOut,
    ToolCreate,
    ToolOut,
    ToolTestRequest,
)
from app.services import agent_runtime, expressions
from app.services.secrets import upsert_secret
from app.services.tools import (
    ApprovalRequired,
    ToolInfo,
    discover_mcp_tools,
    execute_registered_tool,
)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["resources"], dependencies=[Depends(authorize_tenant_request)])


def _require_editor(principal: Principal) -> None:
    if principal.is_api_key or principal.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor required")


def _normalize_base_url(provider: str, base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if provider == "openai_compatible" and "api.deepseek.com" in value:
        if value.endswith("/anthropic") or value.endswith("/beta"):
            return "https://api.deepseek.com/v1"
        if not value.endswith("/v1"):
            return value + "/v1"
    return value


async def _normalize_model_profile(session: AsyncSession, principal: Principal, profile: ModelProfile) -> bool:
    changed = False
    normalized = _normalize_base_url(profile.provider, profile.base_url)
    if normalized != profile.base_url:
        profile.base_url = normalized
        changed = True
    raw_key = profile.api_key_secret or ""
    if raw_key.startswith("sk-") or raw_key.startswith("Bearer "):
        secret_name = f"model_{profile.id}"
        await upsert_secret(
            session,
            principal.tenant_id,
            secret_name,
            raw_key.removeprefix("Bearer "),
            principal.user_id,
        )
        profile.api_key_secret = secret_name
        changed = True
    return changed


@router.get("/tools", response_model=list[ToolOut])
async def list_tools(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[Tool]:
    result = await session.execute(
        select(Tool).where(Tool.tenant_id == principal.tenant_id).order_by(Tool.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/tools", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
async def create_tool(
    payload: ToolCreate,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    _require_editor(principal)
    tool = Tool(
        tenant_id=principal.tenant_id,
        name=payload.name,
        type=payload.type,
        description=payload.description,
        input_schema=payload.input_schema,
        config=payload.config,
        risk_level=payload.risk_level,
        enabled=payload.enabled,
    )
    session.add(tool)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="tool.create",
        resource_type="tool",
        resource_id=tool.id,
        detail={"name": payload.name, "type": payload.type},
        **audit_context(request),
    )
    await session.commit()
    return tool


@router.patch("/tools/{tool_id}", response_model=ToolOut)
async def update_tool(
    tool_id: str,
    payload: ToolCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    _require_editor(principal)
    tool = await session.get(Tool, tool_id)
    if not tool or tool.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool not found")
    tool.name = payload.name
    tool.type = payload.type
    tool.description = payload.description
    tool.input_schema = payload.input_schema
    tool.config = payload.config
    tool.risk_level = payload.risk_level
    tool.enabled = payload.enabled
    await session.commit()
    return tool


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    tool = await session.get(Tool, tool_id)
    if tool and tool.tenant_id == principal.tenant_id:
        await session.delete(tool)
        await session.commit()


@router.get("/mcp-servers", response_model=list[McpServerOut])
async def list_mcp_servers(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[McpServer]:
    result = await session.execute(
        select(McpServer).where(McpServer.tenant_id == principal.tenant_id).order_by(McpServer.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/mcp-servers", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    payload: McpServerCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> McpServer:
    _require_editor(principal)
    server = McpServer(
        tenant_id=principal.tenant_id,
        name=payload.name,
        transport=payload.transport,
        url=payload.url,
        headers=payload.headers,
        enabled=payload.enabled,
    )
    session.add(server)
    await session.commit()
    return server


@router.post("/mcp-servers/{server_id}/discover", response_model=list[McpToolOut])
async def discover(
    server_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[McpTool]:
    _require_editor(principal)
    server = await session.get(McpServer, server_id)
    if not server or server.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mcp server not found")
    tools = await discover_mcp_tools(session, principal.tenant_id, server)
    server.last_discovered_at = utcnow()
    await session.commit()
    return tools


@router.get("/mcp-servers/{server_id}/tools", response_model=list[McpToolOut])
async def list_mcp_tools(
    server_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[McpTool]:
    server = await session.get(McpServer, server_id)
    if not server or server.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mcp server not found")
    result = await session.execute(
        select(McpTool)
        .where(McpTool.tenant_id == principal.tenant_id, McpTool.server_id == server.id)
        .order_by(McpTool.name)
    )
    return list(result.scalars().all())


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    server = await session.get(McpServer, server_id)
    if server and server.tenant_id == principal.tenant_id:
        tools = await session.execute(
            select(Tool).where(Tool.tenant_id == principal.tenant_id, Tool.type == "mcp")
        )
        for tool in tools.scalars().all():
            if str((tool.config or {}).get("server_id") or "") == server.id:
                await session.delete(tool)
        await session.execute(delete(McpTool).where(McpTool.server_id == server.id))
        await session.delete(server)
        await session.commit()


@router.post("/mcp-servers/{server_id}/tools/{mcp_tool_id}/add", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
async def add_mcp_tool(
    server_id: str,
    mcp_tool_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    _require_editor(principal)
    server = await session.get(McpServer, server_id)
    if not server or server.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mcp server not found")
    mcp_tool = await session.get(McpTool, mcp_tool_id)
    if not mcp_tool or mcp_tool.tenant_id != principal.tenant_id or mcp_tool.server_id != server.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mcp tool not found")
    result = await session.execute(
        select(Tool).where(
            Tool.tenant_id == principal.tenant_id,
            Tool.type == "mcp",
            Tool.name == mcp_tool.name,
        )
    )
    tool = result.scalars().first()
    config = {"server_id": server.id, "tool_name": mcp_tool.name}
    if tool:
        tool.description = mcp_tool.description
        tool.input_schema = mcp_tool.input_schema
        tool.config = config
        tool.risk_level = mcp_tool.risk_level
        tool.enabled = True
    else:
        tool = Tool(
            tenant_id=principal.tenant_id,
            name=mcp_tool.name,
            type="mcp",
            description=mcp_tool.description,
            input_schema=mcp_tool.input_schema,
            config=config,
            risk_level=mcp_tool.risk_level,
            enabled=True,
        )
        session.add(tool)
    await session.commit()
    return tool


@router.post("/tools/{tool_id}/test")
async def test_tool(
    tool_id: str,
    payload: ToolTestRequest,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_editor(principal)
    tool = await session.get(Tool, tool_id)
    if not tool or tool.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool not found")
    info = ToolInfo(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        risk_level=tool.risk_level,
        type=tool.type,
        config=tool.config or {},
    )
    try:
        result = await execute_registered_tool(
            session, tenant_id=principal.tenant_id, tool=info, inputs=payload.inputs
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "result": result}


@router.get("/agent-profiles", response_model=list[AgentProfileOut])
async def list_agents(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[AgentProfile]:
    result = await session.execute(
        select(AgentProfile)
        .where(AgentProfile.tenant_id == principal.tenant_id)
        .order_by(AgentProfile.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/agent-profiles", response_model=AgentProfileOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentProfileCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentProfile:
    _require_editor(principal)
    profile = AgentProfile(
        tenant_id=principal.tenant_id,
        name=payload.name,
        role_prompt=payload.role_prompt,
        model_profile_id=payload.model_profile_id,
        tool_ids=payload.tool_ids,
        kb_ids=payload.kb_ids,
        max_iterations=payload.max_iterations,
        output_schema=payload.output_schema,
        temperature=payload.temperature,
    )
    session.add(profile)
    await session.commit()
    return profile


@router.patch("/agent-profiles/{profile_id}", response_model=AgentProfileOut)
async def update_agent(
    profile_id: str,
    payload: AgentProfileCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentProfile:
    _require_editor(principal)
    profile = await session.get(AgentProfile, profile_id)
    if not profile or profile.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent profile not found")
    profile.name = payload.name
    profile.role_prompt = payload.role_prompt
    profile.model_profile_id = payload.model_profile_id
    profile.tool_ids = payload.tool_ids
    profile.kb_ids = payload.kb_ids
    profile.max_iterations = payload.max_iterations
    profile.output_schema = payload.output_schema
    profile.temperature = payload.temperature
    await session.commit()
    return profile


@router.delete("/agent-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    profile_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    profile = await session.get(AgentProfile, profile_id)
    if profile and profile.tenant_id == principal.tenant_id:
        await session.delete(profile)
        await session.commit()


@router.post("/agent-profiles/{profile_id}/test", response_model=AgentTestResponse)
async def test_agent(
    profile_id: str,
    payload: AgentTestRequest,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentTestResponse:
    _require_editor(principal)
    profile = await session.get(AgentProfile, profile_id)
    if not profile or profile.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent profile not found")
    context = expressions.build_context(inputs=payload.inputs, node_outputs={}, run={"id": "preview"})
    goal = payload.goal.strip() or "Use the provided inputs to complete the task."
    history = [item for item in payload.history if isinstance(item, dict)][-40:]
    state = None
    if history:
        state = {
            "messages": history + [{"role": "user", "content": goal}],
            "tokens": 0,
            "iterations": 0,
            "repairs": 0,
            "pending": None,
        }
    try:
        result = await agent_runtime.run_agent(
            session,
            tenant_id=principal.tenant_id,
            profile=profile,
            goal=goal,
            context=context,
            state=state,
            approved_tools=set(),
            agent_name=profile.name,
        )
    except ApprovalRequired as exc:
        return AgentTestResponse(
            requires_approval=True,
            approval={"tool_name": exc.tool_name, "args": exc.arguments, "risk_level": exc.risk_level, "title": exc.title},
            messages=(exc.state or {}).get("messages", [])[-30:],
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    messages = (result.state or {}).get("messages", [])
    return AgentTestResponse(
        output=result.output,
        content=result.content,
        tokens=result.tokens,
        messages=messages[-30:],
    )


@router.get("/model-profiles", response_model=list[ModelProfileOut])
async def list_models(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[ModelProfile]:
    result = await session.execute(
        select(ModelProfile)
        .where(ModelProfile.tenant_id == principal.tenant_id)
        .order_by(ModelProfile.created_at.desc())
    )
    profiles = list(result.scalars().all())
    changed = False
    for profile in profiles:
        changed = await _normalize_model_profile(session, principal, profile) or changed
    if changed:
        await session.commit()
    return profiles


@router.post("/model-profiles", response_model=ModelProfileOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelProfileCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> ModelProfile:
    _require_editor(principal)
    if payload.is_default:
        existing = await session.execute(
            select(ModelProfile).where(ModelProfile.tenant_id == principal.tenant_id)
        )
        for item in existing.scalars().all():
            item.is_default = False
    profile = ModelProfile(
        tenant_id=principal.tenant_id,
        name=payload.name,
        provider=payload.provider,
        base_url=_normalize_base_url(payload.provider, payload.base_url),
        model=payload.model,
        api_key_secret=payload.api_key_secret,
        embedding_dimension=payload.embedding_dimension,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        timeout_sec=payload.timeout_sec,
        is_default=payload.is_default,
    )
    session.add(profile)
    await session.flush()
    raw_key = payload.api_key.strip()
    if not raw_key and payload.api_key_secret.startswith("sk-"):
        raw_key = payload.api_key_secret
        profile.api_key_secret = ""
    if raw_key:
        secret_name = f"model_{profile.id}"
        await upsert_secret(session, principal.tenant_id, secret_name, raw_key.removeprefix("Bearer "), principal.user_id)
        profile.api_key_secret = secret_name
    await session.commit()
    return profile


@router.patch("/model-profiles/{profile_id}", response_model=ModelProfileOut)
async def update_model(
    profile_id: str,
    payload: ModelProfileCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> ModelProfile:
    _require_editor(principal)
    profile = await session.get(ModelProfile, profile_id)
    if not profile or profile.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model profile not found")
    if payload.is_default:
        existing = await session.execute(
            select(ModelProfile).where(ModelProfile.tenant_id == principal.tenant_id)
        )
        for item in existing.scalars().all():
            item.is_default = False
    profile.name = payload.name
    profile.provider = payload.provider
    profile.base_url = _normalize_base_url(payload.provider, payload.base_url)
    profile.model = payload.model
    if payload.api_key_secret:
        profile.api_key_secret = payload.api_key_secret
    profile.embedding_dimension = payload.embedding_dimension
    profile.max_tokens = payload.max_tokens
    profile.temperature = payload.temperature
    profile.timeout_sec = payload.timeout_sec
    profile.is_default = payload.is_default
    raw_key = payload.api_key.strip()
    if not raw_key and payload.api_key_secret.startswith("sk-"):
        raw_key = payload.api_key_secret
    if raw_key:
        secret_name = f"model_{profile.id}"
        await upsert_secret(session, principal.tenant_id, secret_name, raw_key.removeprefix("Bearer "), principal.user_id)
        profile.api_key_secret = secret_name
    await session.commit()
    return profile


@router.delete("/model-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    profile_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    profile = await session.get(ModelProfile, profile_id)
    if profile and profile.tenant_id == principal.tenant_id:
        await session.delete(profile)
        await session.commit()


@router.post("/model-profiles/{profile_id}/test")
async def test_model(
    profile_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    profile = await session.get(ModelProfile, profile_id)
    if not profile or profile.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model profile not found")
    from app.services import model_gateway

    try:
        if await _normalize_model_profile(session, principal, profile):
            await session.commit()
        data = await model_gateway.resolve_chat_profile(session, principal.tenant_id, profile.id)
        result = await model_gateway.chat(data, [{"role": "user", "content": "Reply with OK."}])
        return {"ok": True, "content": result.content[:200], "tokens": result.tokens}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/secrets", response_model=list[SecretOut])
async def list_secrets(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[Secret]:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    result = await session.execute(
        select(Secret).where(Secret.tenant_id == principal.tenant_id).order_by(Secret.name)
    )
    return list(result.scalars().all())


@router.post("/secrets", response_model=SecretOut, status_code=status.HTTP_201_CREATED)
async def create_secret(
    payload: SecretCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Secret:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    secret = await upsert_secret(session, principal.tenant_id, payload.name, payload.value, principal.user_id)
    await session.commit()
    return secret


@router.delete("/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    secret_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    secret = await session.get(Secret, secret_id)
    if secret and secret.tenant_id == principal.tenant_id:
        await session.delete(secret)
        await session.commit()
