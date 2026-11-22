from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Workflow, WorkflowRun, WorkflowVersion
from app.services.workflow_engine import WorkflowEngine


@pytest.mark.asyncio
async def test_start_to_end_executes_and_persists_output():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dsl = {
        "schema_version": "1.0",
        "inputs": {"type": "object", "properties": {}},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "end", "type": "end", "config": {"outputs": {"value": "{{ inputs.value }}"}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "end"}],
        "settings": {"timeout_sec": 30, "max_parallel": 1, "on_error": "fail"},
    }
    canonical = json.dumps(dsl, sort_keys=True, separators=(",", ":"))
    async with session_factory() as session:
        workflow = Workflow(tenant_id="t1", name="Test", draft_dsl=dsl)
        session.add(workflow)
        await session.flush()
        version = WorkflowVersion(
            tenant_id="t1",
            workflow_id=workflow.id,
            version=1,
            dsl=dsl,
            dsl_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )
        session.add(version)
        await session.flush()
        workflow.current_version_id = version.id
        run = WorkflowRun(
            tenant_id="t1",
            workflow_id=workflow.id,
            version_id=version.id,
            status="queued",
            inputs={"value": "hello"},
            state={},
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    async with session_factory() as session:
        await WorkflowEngine(session).execute_run(run_id)
        await session.commit()

    async with session_factory() as session:
        loaded = await session.get(WorkflowRun, run_id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert loaded.output == {"value": "hello"}
