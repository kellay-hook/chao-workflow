from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunEvent


async def emit(
    session: AsyncSession,
    *,
    run_id: str,
    tenant_id: str,
    event_type: str,
    node_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        tenant_id=tenant_id,
        type=event_type,
        node_id=node_id,
        data=data or {},
    )
    session.add(event)
    await session.flush()
    return event
