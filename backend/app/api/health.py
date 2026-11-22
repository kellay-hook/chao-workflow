from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["health"])

RUNS_TOTAL = Counter("flowmind_runs_total", "Workflow runs", ["status"])
PENDING_APPROVALS = Gauge("flowmind_pending_approvals", "Pending approvals")


@router.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await session.execute(text("SELECT 1"))
        return {"ok": True, "database": "ready"}
    except Exception as exc:
        return {"ok": False, "database": str(exc)}


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
