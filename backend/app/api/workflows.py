from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime

from croniter import croniter
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import settings
from app.db import get_session
from app.deps import Principal, audit_context, require_tenant
from app.models import (
    AgentProfile,
    ModelProfile,
    Schedule,
    WebhookEndpoint,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
)
from app.permissions import authorize_tenant_request
from app.schemas import (
    RunCreate,
    RunOut,
    ValidationResult,
    WorkflowCreate,
    WorkflowOut,
    WorkflowTemplateCreate,
    WorkflowUpdate,
    WorkflowVersionOut,
    validate_dsl,
)
from app.services import workflow_templates
from app.services.dispatch import dispatch_run
from app.services.inputs import prepare_run_inputs

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/workflows", tags=["workflows"], dependencies=[Depends(authorize_tenant_request)])


def _default_dsl() -> dict:
    return {
        "schema_version": "1.0",
        "inputs": {"type": "object", "properties": {}},
        "nodes": [
            {"id": "start", "type": "start", "name": "Start", "config": {}, "position": {"x": 80, "y": 160}},
            {"id": "end", "type": "end", "name": "End", "config": {"outputs": {"inputs": "{{ inputs }}"}}, "position": {"x": 520, "y": 160}},
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end", "source_port": "default", "target_port": "default"}],
        "settings": {"timeout_sec": 1800, "max_parallel": 4, "on_error": "fail"},
    }


async def _get_workflow(
    session: AsyncSession, tenant_id: str, workflow_id: str
) -> Workflow:
    workflow = await session.get(Workflow, workflow_id)
    if not workflow or workflow.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
    return workflow


def _require_editor(principal: Principal) -> None:
    if principal.is_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user token required")
    if principal.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor required")


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[Workflow]:
    result = await session.execute(
        select(Workflow)
        .where(Workflow.tenant_id == principal.tenant_id)
        .order_by(Workflow.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Workflow:
    _require_editor(principal)
    workflow = Workflow(
        tenant_id=principal.tenant_id,
        name=payload.name,
        description=payload.description,
        draft_dsl=payload.dsl or _default_dsl(),
        created_by=principal.user_id,
    )
    session.add(workflow)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="workflow.create",
        resource_type="workflow",
        resource_id=workflow.id,
        detail={"name": workflow.name},
        **audit_context(request),
    )
    await session.commit()
    return workflow


@router.get("/templates")
async def list_workflow_templates() -> list[dict]:
    return [template.summary() for template in workflow_templates.WORKFLOW_TEMPLATES]


@router.post("/templates/{template_id}", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow_from_template(
    template_id: str,
    request: Request,
    payload: WorkflowTemplateCreate | None = None,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Workflow:
    _require_editor(principal)
    template = workflow_templates.get_template(template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow template not found")
    dsl = json.loads(json.dumps(template.dsl, ensure_ascii=False))
    model_result = await session.execute(
        select(ModelProfile)
        .where(ModelProfile.tenant_id == principal.tenant_id)
        .order_by(ModelProfile.is_default.desc(), ModelProfile.created_at)
    )
    default_model = model_result.scalars().first()
    agent_result = await session.execute(
        select(AgentProfile)
        .where(AgentProfile.tenant_id == principal.tenant_id)
        .order_by(AgentProfile.created_at)
    )
    tenant_agents = list(agent_result.scalars().all())
    for node in dsl.get("nodes") or []:
        config = node.setdefault("config", {})
        if node.get("type") == "llm" and default_model and not config.get("model_profile_id"):
            config["model_profile_id"] = default_model.id
        if node.get("type") == "agent" and tenant_agents and not config.get("agent_profile_id"):
            config["agent_profile_id"] = tenant_agents[0].id
        if node.get("type") == "agent_team" and tenant_agents:
            if not config.get("supervisor_profile_id"):
                config["supervisor_profile_id"] = tenant_agents[0].id
            if not config.get("worker_profile_ids"):
                config["worker_profile_ids"] = [agent.id for agent in tenant_agents[:3]]
    workflow_name = (payload.name if payload and payload.name else template.name).strip()
    workflow_description = payload.description if payload and payload.description is not None else template.description
    workflow = Workflow(
        tenant_id=principal.tenant_id,
        name=workflow_name,
        description=workflow_description,
        draft_dsl=dsl,
        created_by=principal.user_id,
    )
    session.add(workflow)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="workflow.create_from_template",
        resource_type="workflow",
        resource_id=workflow.id,
        detail={"template_id": template.id, "name": workflow_name},
        **audit_context(request),
    )
    await session.commit()
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Workflow:
    return await _get_workflow(session, principal.tenant_id, workflow_id)


@router.patch("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Workflow:
    _require_editor(principal)
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    if payload.version_no is not None and payload.version_no != workflow.version_no:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="draft version conflict")
    if payload.name is not None:
        workflow.name = payload.name
    if payload.description is not None:
        workflow.description = payload.description
    if payload.dsl is not None:
        workflow.draft_dsl = payload.dsl
    await session.commit()
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    await session.delete(workflow)
    await session.commit()


@router.post("/{workflow_id}/validate", response_model=ValidationResult)
async def validate_workflow(
    workflow_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> ValidationResult:
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    return validate_dsl(workflow.draft_dsl)


@router.post("/{workflow_id}/publish", response_model=WorkflowVersionOut)
async def publish_workflow(
    workflow_id: str,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> WorkflowVersion:
    _require_editor(principal)
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    result = validate_dsl(workflow.draft_dsl)
    if not result.valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.model_dump())
    if principal.role not in {"owner", "admin"}:
        code_nodes = [node for node in workflow.draft_dsl.get("nodes", []) if node.get("type") == "code"]
        if code_nodes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin approval required for code nodes")
    canonical = json.dumps(workflow.draft_dsl, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    dsl_hash = hashlib.sha256(canonical.encode()).hexdigest()
    version = WorkflowVersion(
        tenant_id=principal.tenant_id,
        workflow_id=workflow.id,
        version=workflow.version_no + 1,
        dsl=workflow.draft_dsl,
        dsl_hash=dsl_hash,
        published_by=principal.user_id,
    )
    session.add(version)
    await session.flush()
    workflow.version_no = version.version
    workflow.current_version_id = version.id
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="workflow.publish",
        resource_type="workflow",
        resource_id=workflow.id,
        detail={"version": version.version, "hash": dsl_hash},
        **audit_context(request),
    )
    await session.commit()
    return version


@router.get("/{workflow_id}/versions", response_model=list[WorkflowVersionOut])
async def list_versions(
    workflow_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowVersion]:
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    result = await session.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow.id)
        .order_by(WorkflowVersion.version.desc())
    )
    return list(result.scalars().all())


@router.post("/{workflow_id}/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_workflow(
    workflow_id: str,
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRun:
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    if not workflow.current_version_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="publish the workflow first")
    version = await session.get(WorkflowVersion, workflow.current_version_id)
    if not version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="published version not found")
    prepared_inputs, missing = prepare_run_inputs(version.dsl, payload.inputs)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Missing required workflow inputs", "missing": missing},
        )
    if payload.idempotency_key:
        existing = await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == principal.tenant_id,
                WorkflowRun.idempotency_key == payload.idempotency_key,
            )
        )
        found = existing.scalar_one_or_none()
        if found:
            return found
    run = WorkflowRun(
        tenant_id=principal.tenant_id,
        workflow_id=workflow.id,
        version_id=version.id,
        status="queued",
        trigger_type="manual",
        inputs=prepared_inputs,
        idempotency_key=payload.idempotency_key,
        created_by=principal.user_id,
        state={},
    )
    session.add(run)
    await session.flush()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="run.start",
        resource_type="workflow_run",
        resource_id=run.id,
        detail={"workflow_id": workflow.id, "version_id": version.id},
    )
    await session.commit()
    dispatch_run(run.id, background_tasks)
    return run


@router.get("/{workflow_id}/schedules")
async def list_schedules(
    workflow_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    result = await session.execute(select(Schedule).where(Schedule.workflow_id == workflow.id))
    return [
        {
            "id": item.id,
            "cron": item.cron,
            "timezone": item.timezone,
            "enabled": item.enabled,
            "next_run_at": item.next_run_at,
        }
        for item in result.scalars().all()
    ]


@router.post("/{workflow_id}/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    workflow_id: str,
    payload: dict,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_editor(principal)
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    cron = str(payload.get("cron") or "")
    tz = str(payload.get("timezone") or "Asia/Shanghai")
    if not croniter.is_valid(cron):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cron expression")
    next_run = croniter(cron, datetime.now(UTC)).get_next(datetime)
    schedule = Schedule(
        tenant_id=principal.tenant_id,
        workflow_id=workflow.id,
        cron=cron,
        timezone=tz,
        enabled=True,
        next_run_at=next_run,
        created_by=principal.user_id,
    )
    session.add(schedule)
    await session.commit()
    return {"id": schedule.id, "cron": cron, "next_run_at": next_run}


@router.delete("/{workflow_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    workflow_id: str,
    schedule_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    schedule = await session.get(Schedule, schedule_id)
    if schedule and schedule.tenant_id == principal.tenant_id and schedule.workflow_id == workflow_id:
        await session.delete(schedule)
        await session.commit()


@router.post("/{workflow_id}/webhooks", status_code=status.HTTP_201_CREATED)
async def create_webhook(
    workflow_id: str,
    payload: dict,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_editor(principal)
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    token = "wh_" + secrets.token_urlsafe(32)
    require_signature = bool(payload.get("require_signature", True))
    secret = secrets.token_urlsafe(32) if require_signature else ""
    endpoint = WebhookEndpoint(
        tenant_id=principal.tenant_id,
        workflow_id=workflow.id,
        name=str(payload.get("name") or "Webhook"),
        token=token,
        hmac_secret=secret,
    )
    session.add(endpoint)
    await session.commit()
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "url": f"{settings.public_base_url}/api/v1/hooks/{token}",
        "hmac_secret": secret,
        "require_signature": require_signature,
    }


@router.get("/{workflow_id}/webhooks")
async def list_webhooks(
    workflow_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    result = await session.execute(select(WebhookEndpoint).where(WebhookEndpoint.workflow_id == workflow.id))
    base = settings.public_base_url.rstrip("/")
    return [
        {
            "id": item.id,
            "name": item.name,
            "enabled": item.enabled,
            "url": f"{base}/api/v1/hooks/{item.token}",
            "require_signature": bool(item.hmac_secret),
            "created_at": item.created_at.isoformat(),
        }
        for item in result.scalars().all()
    ]


@router.delete("/{workflow_id}/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    workflow_id: str,
    webhook_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    await _get_workflow(session, principal.tenant_id, workflow_id)
    endpoint = await session.get(WebhookEndpoint, webhook_id)
    if endpoint and endpoint.tenant_id == principal.tenant_id and endpoint.workflow_id == workflow_id:
        await session.delete(endpoint)
        await session.commit()


@router.post("/{workflow_id}/webhooks/{webhook_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_webhook(
    workflow_id: str,
    webhook_id: str,
    background_tasks: BackgroundTasks,
    payload: dict | None = None,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_editor(principal)
    workflow = await _get_workflow(session, principal.tenant_id, workflow_id)
    endpoint = await session.get(WebhookEndpoint, webhook_id)
    if not endpoint or endpoint.tenant_id != principal.tenant_id or endpoint.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="webhook not found")
    if not workflow.current_version_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workflow is not published")
    test_payload = payload or {
        "event": "demo.order.created",
        "id": f"evt_demo_{secrets.token_hex(4)}",
        "data": {"order_id": "A1001", "amount": 299, "customer": "Demo User"},
    }
    run = WorkflowRun(
        tenant_id=principal.tenant_id,
        workflow_id=workflow.id,
        version_id=workflow.current_version_id,
        status="queued",
        trigger_type="webhook",
        trigger_payload={"payload": test_payload, "test": True},
        inputs={"webhook": test_payload},
        created_by=principal.user_id,
        state={},
    )
    session.add(run)
    await session.commit()
    dispatch_run(run.id, background_tasks)
    return {"run_id": run.id, "status": "queued", "payload": test_payload}

