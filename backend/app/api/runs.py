from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_session
from app.deps import Principal, require_tenant
from app.models import NodeRun, RunEvent, Workflow, WorkflowRun, utcnow
from app.permissions import authorize_tenant_request
from app.schemas import NodeRunOut, RunOut
from app.services.dispatch import dispatch_run

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/runs", tags=["runs"], dependencies=[Depends(authorize_tenant_request)])


async def _get_run(session: AsyncSession, tenant_id: str, run_id: str) -> WorkflowRun:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(
    workflow_id: str | None = None,
    run_status: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowRun]:
    stmt = select(WorkflowRun).where(WorkflowRun.tenant_id == principal.tenant_id)
    if workflow_id:
        stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
    if run_status:
        stmt = stmt.where(WorkflowRun.status == run_status)
    stmt = stmt.order_by(WorkflowRun.created_at.desc()).limit(min(limit, 200))
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRun:
    return await _get_run(session, principal.tenant_id, run_id)


@router.get("/{run_id}/nodes", response_model=list[NodeRunOut])
async def get_nodes(
    run_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[NodeRun]:
    await _get_run(session, principal.tenant_id, run_id)
    result = await session.execute(
        select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.created_at)
    )
    return list(result.scalars().all())


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    principal: Principal = Depends(require_tenant),
) -> StreamingResponse:
    async def generator() -> AsyncIterator[bytes]:
        last_id = 0
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            last_id = int(header)
        idle = 0.0
        while True:
            if await request.is_disconnected():
                break
            async with SessionLocal() as session:
                run = await session.get(WorkflowRun, run_id)
                if not run or run.tenant_id != principal.tenant_id:
                    yield b"event: error\ndata: {\"message\":\"run not found\"}\n\n"
                    break
                result = await session.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                    .order_by(RunEvent.id)
                    .limit(100)
                )
                events = list(result.scalars().all())
                terminal = run.status in {"succeeded", "failed", "canceled", "timed_out"}
                payloads = []
                for event in events:
                    last_id = event.id
                    payloads.append(
                        f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"
                    )
                current_status = run.status
            if payloads:
                idle = 0.0
                for payload in payloads:
                    yield payload.encode()
            else:
                idle += 1.0
                if idle >= 15:
                    yield b": heartbeat\n\n"
                    idle = 0.0
            if terminal and not payloads:
                yield f"event: run.status\ndata: {json.dumps({'status': current_status})}\n\n".encode()
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRun:
    run = await _get_run(session, principal.tenant_id, run_id)
    if run.status in {"succeeded", "failed", "canceled"}:
        return run
    run.cancel_requested = True
    if run.status == "queued":
        run.status = "canceled"
        run.finished_at = utcnow()
    await session.commit()
    return run


@router.post("/{run_id}/retry", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRun:
    previous = await _get_run(session, principal.tenant_id, run_id)
    workflow = await session.get(Workflow, previous.workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
    run = WorkflowRun(
        tenant_id=principal.tenant_id,
        workflow_id=previous.workflow_id,
        version_id=previous.version_id,
        status="queued",
        trigger_type="retry",
        inputs=previous.inputs,
        created_by=principal.user_id,
        state={},
    )
    session.add(run)
    await session.commit()
    dispatch_run(run.id, background_tasks)
    return run
