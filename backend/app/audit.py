from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail or {},
            ip=ip,
            request_id=request_id,
        )
    )
