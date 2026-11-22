from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.db import Base
from app.models import Document, KnowledgeBase
from app.services import dispatch, rag
from app.services.storage import StorageError


@pytest.mark.asyncio
async def test_interrupted_ingestion_is_marked_failed(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recover.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        kb = KnowledgeBase(tenant_id="tenant-1", name="KB", description="")
        session.add(kb)
        await session.flush()
        document = Document(
            tenant_id="tenant-1",
            kb_id=kb.id,
            filename="interrupted.md",
            mime_type="text/markdown",
            size=10,
            sha256="hash",
            storage_key="missing/file.md",
            status="processing",
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    monkeypatch.setattr("app.db.SessionLocal", Session)
    recovered = await dispatch.recover_interrupted_ingestions()
    assert recovered == 1

    async with Session() as session:
        item = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
        assert item.status == "failed"
        assert "解析任务被中断" in item.error


@pytest.mark.asyncio
async def test_ingestion_failure_exposes_actionable_error(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ingest.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        kb = KnowledgeBase(tenant_id="tenant-1", name="KB", description="", chunk_size=800, chunk_overlap=100)
        session.add(kb)
        await session.flush()
        document = Document(
            tenant_id="tenant-1",
            kb_id=kb.id,
            filename="missing.md",
            mime_type="text/markdown",
            size=10,
            sha256="hash",
            storage_key="missing/file.md",
            status="pending",
        )
        session.add(document)
        await session.commit()
        document_id = document.id

        with pytest.raises(StorageError):
            await rag.ingest_document(session, document_id)
        await session.commit()

    async with Session() as session:
        item = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
        assert item.status == "failed"
        assert item.error