from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import Principal, require_tenant
from app.models import AgentProfile, AgentSession
from app.permissions import authorize_tenant_request
from app.schemas import (
    AgentSessionCreate,
    AgentSessionMessageRequest,
    AgentSessionOut,
    AgentSessionSummary,
    AgentSessionUpdate,
    AgentTestResponse,
)
from app.services import agent_runtime, expressions
from app.services.tools import ApprovalRequired

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/agent-sessions", tags=["agent-sessions"], dependencies=[Depends(authorize_tenant_request)])


@router.get("", response_model=list[AgentSessionSummary])
async def list_sessions(
    agent_profile_id: str | None = None,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[AgentSessionSummary]:
    stmt = select(AgentSession).where(AgentSession.tenant_id == principal.tenant_id)
    if agent_profile_id:
        stmt = stmt.where(AgentSession.agent_profile_id == agent_profile_id)
    result = await session.execute(stmt.order_by(AgentSession.updated_at.desc()).limit(100))
    return [
        AgentSessionSummary(
            id=item.id,
            tenant_id=item.tenant_id,
            agent_profile_id=item.agent_profile_id,
            user_id=item.user_id,
            title=item.title,
            tokens=item.tokens,
            message_count=len(item.messages or []),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in result.scalars().all()
    ]


@router.post("", response_model=AgentSessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: AgentSessionCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentSession:
    profile = await session.get(AgentProfile, payload.agent_profile_id)
    if not profile or profile.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent profile not found")
    item = AgentSession(tenant_id=principal.tenant_id, agent_profile_id=payload.agent_profile_id, user_id=principal.user_id, title=payload.title or "New conversation", messages=[])
    session.add(item)
    await session.commit()
    return item


@router.get("/{session_id}", response_model=AgentSessionOut)
async def get_session_detail(
    session_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentSession:
    item = await session.get(AgentSession, session_id)
    if not item or item.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent session not found")
    return item


@router.patch("/{session_id}", response_model=AgentSessionOut)
async def rename_session(
    session_id: str,
    payload: AgentSessionUpdate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentSession:
    item = await session.get(AgentSession, session_id)
    if not item or item.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent session not found")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title required")
    item.title = title
    await session.commit()
    return item


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    item = await session.get(AgentSession, session_id)
    if item and item.tenant_id == principal.tenant_id:
        await session.delete(item)
        await session.commit()


@router.post("/{session_id}/messages", response_model=AgentTestResponse)
async def send_message(
    session_id: str,
    payload: AgentSessionMessageRequest,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> AgentTestResponse:
    item = await session.get(AgentSession, session_id)
    if not item or item.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent session not found")
    profile = await session.get(AgentProfile, item.agent_profile_id)
    if not profile or profile.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent profile not found")
    history = [message for message in (item.messages or []) if isinstance(message, dict)][-60:]
    state = None
    if history:
        state = {"messages": history + [{"role": "user", "content": payload.goal}], "tokens": 0, "iterations": 0, "repairs": 0, "pending": None}
    context = expressions.build_context(inputs=payload.inputs, node_outputs={}, run={"id": f"session:{item.id}"})
    try:
        result = await agent_runtime.run_agent(session, tenant_id=principal.tenant_id, profile=profile, goal=payload.goal, context=context, state=state, approved_tools=set(), agent_name=profile.name)
    except ApprovalRequired as exc:
        item.messages = history + [{"role": "user", "content": payload.goal}]
        await session.commit()
        return AgentTestResponse(requires_approval=True, approval={"tool_name": exc.tool_name, "args": exc.arguments, "risk_level": exc.risk_level, "title": exc.title}, messages=item.messages, session_id=item.id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    item.messages = (result.state or {}).get("messages", [])
    item.tokens += result.tokens
    if item.title in {"New conversation", "新对话"}:
        item.title = payload.goal[:80]
    await session.commit()
    return AgentTestResponse(output=result.output, content=result.content, tokens=result.tokens, messages=item.messages, session_id=item.id)
