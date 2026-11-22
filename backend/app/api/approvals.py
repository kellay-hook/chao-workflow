from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import Principal, audit_context, require_tenant
from app.models import Approval, WorkflowRun, is_expired, utcnow
from app.permissions import authorize_tenant_request
from app.schemas import ApprovalDecision, ApprovalOut
from app.services.dispatch import dispatch_resume

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/approvals", tags=["approvals"], dependencies=[Depends(authorize_tenant_request)])


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    approval_status: str | None = "pending",
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[Approval]:
    stmt = select(Approval).where(Approval.tenant_id == principal.tenant_id)
    if approval_status:
        stmt = stmt.where(Approval.status == approval_status)
    result = await session.execute(stmt.order_by(Approval.created_at.desc()).limit(200))
    approvals = list(result.scalars().all())
    for approval in approvals:
        if approval.status == "pending" and is_expired(approval.expires_at):
            approval.status = "expired"
    await session.commit()
    return [item for item in approvals if not approval_status or item.status == approval_status]


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: str,
    payload: ApprovalDecision,
    background_tasks: BackgroundTasks,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Approval:
    return await _decide(
        approval_id,
        approved=True,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
        background_tasks=background_tasks,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: str,
    payload: ApprovalDecision,
    background_tasks: BackgroundTasks,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Approval:
    return await _decide(
        approval_id,
        approved=False,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
        background_tasks=background_tasks,
    )


async def _decide(
    approval_id: str,
    *,
    approved: bool,
    payload: ApprovalDecision,
    request: Request,
    principal: Principal,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> Approval:
    if principal.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor required")
    approval = await session.get(Approval, approval_id)
    if not approval or approval.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="approval already resolved")
    if is_expired(approval.expires_at):
        approval.status = "expired"
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="approval expired")
    approval.status = "approved" if approved else "rejected"
    approval.decided_by = principal.user_id
    approval.decided_at = utcnow()
    approval.comment = payload.comment
    run = await session.get(WorkflowRun, approval.run_id)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="approval.approve" if approved else "approval.reject",
        resource_type="approval",
        resource_id=approval.id,
        detail={"run_id": approval.run_id, "comment": payload.comment},
        **audit_context(request),
    )
    await session.commit()
    if run:
        dispatch_resume(
            run.id,
            {
                "approved": approved,
                "node_id": approval.node_id,
                "tool_name": approval.tool_name,
                "comment": payload.comment,
                "approval_id": approval.id,
            },
            background_tasks,
        )
    return approval

