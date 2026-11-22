from __future__ import annotations

import asyncio

from croniter import croniter
from sqlalchemy import select

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import Schedule, Workflow, WorkflowRun, ensure_aware, utcnow
from app.services.rag import ingest_document
from app.services.workflow_engine import WorkflowEngine


async def _execute(run_id: str, resume: dict | None = None) -> None:
    async with SessionLocal() as session:
        await WorkflowEngine(session).execute_run(run_id, resume=resume)
        await session.commit()


@celery_app.task(name="flowmind.execute_run")
def execute_run_task(run_id: str) -> None:
    asyncio.run(_execute(run_id))


@celery_app.task(name="flowmind.resume_run")
def resume_run_task(run_id: str, resume: dict) -> None:
    asyncio.run(_execute(run_id, resume=resume))


async def _ingest(document_id: str) -> None:
    async with SessionLocal() as session:
        await ingest_document(session, document_id)
        await session.commit()


@celery_app.task(name="flowmind.ingest_document")
def ingest_document_task(document_id: str) -> None:
    asyncio.run(_ingest(document_id))


async def _scan_schedules() -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Schedule).where(Schedule.enabled.is_(True)))
        schedules = list(result.scalars().all())
        now = utcnow()
        for schedule in schedules:
            if schedule.next_run_at and ensure_aware(schedule.next_run_at) > now:
                continue
            workflow = await session.get(Workflow, schedule.workflow_id)
            if not workflow or not workflow.current_version_id:
                continue
            slot = schedule.next_run_at.isoformat() if schedule.next_run_at else now.isoformat()
            key = f"schedule:{schedule.id}:{slot}"[:200]
            existing = await session.execute(
                select(WorkflowRun.id).where(
                    WorkflowRun.tenant_id == schedule.tenant_id,
                    WorkflowRun.idempotency_key == key,
                )
            )
            if existing.scalar_one_or_none():
                continue
            run = WorkflowRun(
                tenant_id=schedule.tenant_id,
                workflow_id=workflow.id,
                version_id=workflow.current_version_id,
                status="queued",
                trigger_type="schedule",
                trigger_payload={"schedule_id": schedule.id, "slot": slot},
                inputs={},
                idempotency_key=key,
                state={},
            )
            session.add(run)
            await session.flush()
            schedule.next_run_at = croniter(schedule.cron, now).get_next(type(now))
            await session.flush()
            execute_run_task.delay(run.id)
        await session.commit()


@celery_app.task(name="flowmind.scan_schedules")
def scan_schedules_task() -> None:
    asyncio.run(_scan_schedules())

