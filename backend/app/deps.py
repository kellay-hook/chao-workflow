from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import ApiKey, Membership, User
from app.security import AuthError, decode_access_token, hash_token

bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"viewer": 10, "runner": 20, "editor": 30, "admin": 40, "owner": 50}


@dataclass
class Principal:
    user_id: str | None
    tenant_id: str
    role: str
    scopes: list[str]
    auth_type: str
    request_id: str | None = None

    @property
    def is_api_key(self) -> bool:
        return self.auth_type == "api_key"


async def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")
    token = credentials.credentials
    if token.startswith("wfk_"):
        key_hash = hash_token(token)
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
        return Principal(
            user_id=api_key.created_by,
            tenant_id=api_key.tenant_id,
            role="runner",
            scopes=list(api_key.scopes or []),
            auth_type="api_key",
            request_id=getattr(request.state, "request_id", None),
        )
    try:
        payload = decode_access_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return Principal(
        user_id=str(payload["sub"]),
        tenant_id=str(payload["tenant_id"]),
        role=str(payload.get("role", "viewer")),
        scopes=["*"],
        auth_type="jwt",
        request_id=getattr(request.state, "request_id", None),
    )


async def get_current_user(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not principal.user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user required")
    user = await session.get(User, principal.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user disabled")
    return user


async def require_tenant(
    tenant_id: str,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if principal.is_api_key:
        if principal.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
        return principal
    result = await session.execute(
        select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.user_id == principal.user_id
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a member")
    return Principal(
        user_id=principal.user_id,
        tenant_id=tenant_id,
        role=membership.role,
        scopes=principal.scopes,
        auth_type=principal.auth_type,
        request_id=principal.request_id,
    )


def require_role(*roles: str):
    minimum = min(ROLE_RANK.get(role, 0) for role in roles)

    async def checker(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.is_api_key and "run" in principal.scopes:
            if minimum <= ROLE_RANK["runner"]:
                return principal
        if ROLE_RANK.get(principal.role, 0) < minimum:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return principal

    return checker


def can_write(principal: Principal, minimum: str = "editor") -> bool:
    if principal.is_api_key:
        return "run" in principal.scopes
    return ROLE_RANK.get(principal.role, 0) >= ROLE_RANK[minimum]


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def audit_context(request: Request) -> dict[str, Any]:
    return {
        "ip": client_ip(request),
        "request_id": getattr(request.state, "request_id", None),
    }
