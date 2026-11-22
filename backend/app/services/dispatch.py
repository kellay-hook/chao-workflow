from __future__ import annotations

import asyncio
import logging

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)


async def _run_inline(run_id: str, resume: dict | None = None) -> None:
    from app.db import SessionLocal
    from app.services.workflow_engine import WorkflowEngine

    try:
        async with SessionLocal() as session:
            await WorkflowEngine(session).execute_run(run_id, resume=resume)
            await session.commit()
    except Exception:
        logger.exception("inline workflow run failed", extra={"run_id": run_id})


def dispatch_run(run_id: str, background_tasks: BackgroundTasks | None = None) -> None:
    if settings.run_inline:
        if background_tasks is not None:
            background_tasks.add_task(_run_inline, run_id)
        else:
            asyncio.create_task(_run_inline(run_id))
        return
    from app.tasks import execute_run_task

    execute_run_task.delay(run_id)


def dispatch_resume(run_id: str, resume: dict, background_tasks: BackgroundTasks | None = None) -> None:
    if settings.run_inline:
        if background_tasks is not None:
            background_tasks.add_task(_run_inline, run_id, resume)
        else:
            asyncio.create_task(_run_inline(run_id, resume))
        return
    from app.tasks import resume_run_task

    resume_run_task.delay(run_id, resume)


async def recover_interrupted_ingestions() -> int:
    """Mark documents left pending by a previous process as failed so users can retry."""
    from app.db import SessionLocal
    from app.models import Document

    async with SessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.status.in_(["pending", "processing"]))
        )
        documents = list(result.scalars().all())
        for document in documents:
            document.status = "failed"
            document.error = "解析任务被中断（服务重启），请点击「重解析」重新处理。"
        if documents:
            await session.commit()
        return len(documents)


def dispatch_ingest(document_id: str, background_tasks: BackgroundTasks | None = None) -> None:
    if settings.run_inline:
        from app.db import SessionLocal
        from app.services.rag import ingest_document

        async def _inline() -> None:
            async with SessionLocal() as session:
                try:
                    await ingest_document(session, document_id)
                    await session.commit()
                except Exception as exc:
                    logger.exception("inline ingestion failed", extra={"document_id": document_id})
                    try:
                        await session.rollback()
                        from app.models import Document

                        document = await session.get(Document, document_id)
                        if document and document.status != "ready":
                            document.status = "failed"
                            document.error = str(exc)[:2000]
                            await session.commit()
                    except Exception:
                        logger.exception(
                            "could not mark document as failed",
                            extra={"document_id": document_id},
                        )

        if background_tasks is not None:
            background_tasks.add_task(_inline)
        else:
            asyncio.create_task(_inline())
        return
    from app.tasks import ingest_document_task

    ingest_document_task.delay(document_id)
