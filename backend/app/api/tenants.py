from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import settings
from app.db import get_session
from app.deps import Principal, audit_context, get_current_user, require_tenant
from app.models import (
    ApiKey,
    AuditLog,
    Invitation,
    Membership,
    Tenant,
    User,
    WorkflowRun,
    utcnow,
)
from app.permissions import permission_payload
from app.schemas import (
    ApiKeyOut,
    AuditOut,
    InviteRequest,
    MemberRoleUpdate,
    MembershipOut,
    PermissionSummary,
    TenantCreateRequest,
    TenantOut,
    UsageOut,
    slugify,
)
from app.security import new_api_key, new_email_token
from app.services.email import send_email

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[Tenant]:
    result = await session.execute(
        select(Tenant)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user.id)
        .order_by(Tenant.created_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    base = slugify(payload.name)
    candidate = base
    suffix = 1
    while (await session.execute(select(Tenant.id).where(Tenant.slug == candidate))).scalar_one_or_none():
        suffix += 1
        candidate = f"{base[:55]}-{suffix}"
    tenant = Tenant(name=payload.name, slug=candidate, created_by=user.id, settings={})
    session.add(tenant)
    await session.flush()
    session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
    await audit(
        session,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="tenant.create",
        resource_type="tenant",
        resource_id=tenant.id,
        **audit_context(request),
    )
    await session.commit()
    return tenant


@router.get("/{tenant_id}/members", response_model=list[MembershipOut])
async def list_members(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[MembershipOut]:
    result = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == principal.tenant_id)
        .order_by(Membership.created_at)
    )
    return [
        MembershipOut(
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            role=membership.role,
            email=user.email,
            name=user.name,
        )
        for membership, user in result.all()
    ]


@router.get("/{tenant_id}/permissions/me", response_model=PermissionSummary)
async def my_permissions(
    principal: Principal = Depends(require_tenant),
) -> PermissionSummary:
    return PermissionSummary(**permission_payload(principal.role))


@router.patch("/{tenant_id}/members/{user_id}")
async def update_member_role(
    user_id: str,
    payload: MemberRoleUpdate,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    result = await session.execute(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id, Membership.user_id == user_id
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    if target.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cannot modify workspace owner")
    if target.user_id == principal.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cannot change your own role")
    if principal.role != "owner" and (payload.role == "admin" or target.role == "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="only owner can manage admin roles")
    previous = target.role
    target.role = payload.role
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="member.role_update",
        resource_type="membership",
        resource_id=target.id,
        detail={"user_id": user_id, "from": previous, "to": payload.role},
        **audit_context(request),
    )
    await session.commit()
    return {"ok": True, "user_id": user_id, "role": payload.role}


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: str,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    result = await session.execute(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id, Membership.user_id == user_id
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    if target.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cannot remove workspace owner")
    if target.user_id == principal.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cannot remove yourself")
    if target.role == "admin" and principal.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="only owner can remove admins")
    await session.delete(target)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="member.remove",
        resource_type="membership",
        resource_id=target.id,
        detail={"user_id": user_id, "role": target.role},
        **audit_context(request),
    )
    await session.commit()


@router.post("/{tenant_id}/invitations", status_code=status.HTTP_201_CREATED)
async def invite_member(
    payload: InviteRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not principal.is_api_key and principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    if payload.role == "admin" and principal.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="only owner can invite admins")
    raw, token_hash = new_email_token()
    invitation = Invitation(
        tenant_id=principal.tenant_id,
        email=payload.email.lower(),
        role=payload.role,
        token_hash=token_hash,
        invited_by=principal.user_id,
        expires_at=utcnow() + timedelta(days=7),
    )
    session.add(invitation)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="member.invite",
        resource_type="invitation",
        resource_id=invitation.id,
        detail={"email": payload.email, "role": payload.role},
        **audit_context(request),
    )
    await session.commit()
    background_tasks.add_task(
        send_email,
        payload.email,
        "You are invited to FlowMind",
        f"Join here: {settings.public_base_url}/accept-invite?token={raw}",
    )
    return {"ok": True, "invitation_id": invitation.id}


@router.get("/{tenant_id}/audit", response_model=list[AuditOut])
async def list_audit(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
    limit: int = 100,
) -> list[AuditLog]:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == principal.tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 500))
    )
    return list(result.scalars().all())


@router.get("/{tenant_id}/usage", response_model=UsageOut)
async def usage(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> UsageOut:
    since = utcnow() - timedelta(days=30)
    result = await session.execute(
        select(
            func.count(WorkflowRun.id),
            func.coalesce(func.sum(WorkflowRun.token_usage), 0),
        ).where(WorkflowRun.tenant_id == principal.tenant_id, WorkflowRun.created_at >= since)
    )
    runs, tokens = result.one()
    return UsageOut(
        runs=int(runs or 0),
        llm_tokens=int(tokens or 0),
        embedding_tokens=0,
        runner_seconds=0,
        storage_bytes=0,
    )


@router.get("/{tenant_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKey]:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{tenant_id}/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    name: str,
    request: Request,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    raw, prefix, key_hash = new_api_key()
    key = ApiKey(
        tenant_id=principal.tenant_id,
        name=name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=["run"],
        created_by=principal.user_id,
    )
    session.add(key)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="api_key.create",
        resource_type="api_key",
        resource_id=key.id,
        detail={"name": name},
        **audit_context(request),
    )
    await session.commit()
    return {"id": key.id, "name": key.name, "key": raw, "prefix": prefix}


@router.delete("/{tenant_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    key = await session.get(ApiKey, key_id)
    if key and key.tenant_id == principal.tenant_id:
        key.revoked_at = utcnow()
        await session.commit()


@router.get("/{tenant_id}/settings")
async def get_settings(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = await session.get(Tenant, principal.tenant_id)
    return tenant.settings if tenant else {}


@router.patch("/{tenant_id}/settings")
async def update_settings(
    payload: dict,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    tenant = await session.get(Tenant, principal.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    allowed = {"allowed_http_domains", "max_concurrent_runs", "require_approval_for_medium"}
    tenant.settings = {**tenant.settings, **{key: value for key, value in payload.items() if key in allowed}}
    await session.commit()
    return tenant.settings
