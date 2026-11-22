from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import WebhookEndpoint, Workflow, WorkflowRun
from app.services.dispatch import dispatch_run

router = APIRouter(prefix="/api/v1/hooks", tags=["hooks"])


@router.post("/{token}", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.token == token, WebhookEndpoint.enabled.is_(True)
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="webhook not found")
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="payload too large")
    if endpoint.hmac_secret:
        signature = request.headers.get("x-webhook-signature", "")
        expected = "sha256=" + hmac.new(
            endpoint.hmac_secret.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON") from exc
    idempotency_key = request.headers.get("idempotency-key")
    if not idempotency_key and isinstance(payload, dict):
        idempotency_key = payload.get("id") or payload.get("event_id")
    workflow = await session.get(Workflow, endpoint.workflow_id)
    if not workflow or not workflow.current_version_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workflow is not published")
    if idempotency_key:
        existing = await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == endpoint.tenant_id,
                WorkflowRun.idempotency_key == f"webhook:{idempotency_key}"[:200],
            )
        )
        found = existing.scalar_one_or_none()
        if found:
            return {"run_id": found.id, "status": found.status, "duplicate": True}
    run = WorkflowRun(
        tenant_id=endpoint.tenant_id,
        workflow_id=workflow.id,
        version_id=workflow.current_version_id,
        status="queued",
        trigger_type="webhook",
        trigger_payload={"payload": payload, "headers": dict(request.headers)},
        inputs={"webhook": payload},
        idempotency_key=f"webhook:{idempotency_key}"[:200] if idempotency_key else None,
        state={},
    )
    session.add(run)
    await session.commit()
    dispatch_run(run.id, background_tasks)
    return {"run_id": run.id, "status": "queued"}
