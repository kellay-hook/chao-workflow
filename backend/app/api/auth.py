from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import settings
from app.db import get_session
from app.deps import Principal, audit_context, get_current_user, get_principal
from app.models import (
    EmailToken,
    Invitation,
    Membership,
    RefreshToken,
    Tenant,
    User,
    is_expired,
    utcnow,
)
from app.schemas import (
    AcceptInviteRequest,
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TenantOut,
    UserOut,
    VerifyEmailRequest,
    slugify,
)
from app.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_email_token,
    new_refresh_token,
    verify_password,
)
from app.services.email import send_email

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
COOKIE_NAME = "flowmind_refresh"


def _tenant_out(tenant: Tenant) -> TenantOut:
    return TenantOut.model_validate(tenant)


async def _memberships(session: AsyncSession, user_id: str) -> list[tuple[Tenant, str]]:
    result = await session.execute(
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user_id)
        .order_by(Tenant.created_at)
    )
    return [(row[0], row[1]) for row in result.all()]


async def _auth_response(
    session: AsyncSession, user: User, response: Response, verification_token: str | None = None
) -> AuthResponse:
    pairs = await _memberships(session, user.id)
    active = pairs[0] if pairs else (None, "viewer")
    access, expires_in = create_access_token(
        user.id, active[0].id if active[0] else "", active[1]
    )
    raw_refresh, refresh_hash, refresh_expires = new_refresh_token()
    session.add(
        RefreshToken(user_id=user.id, token_hash=refresh_hash, expires_at=refresh_expires)
    )
    response.set_cookie(
        COOKIE_NAME,
        raw_refresh,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        max_age=settings.refresh_token_days * 86400,
        path="/",
    )
    return AuthResponse(
        access_token=access,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
        tenants=[_tenant_out(pair[0]) for pair in pairs],
        active_tenant=_tenant_out(active[0]) if active[0] else None,
        verification_token=verification_token,
    )


async def _unique_slug(session: AsyncSession, base: str) -> str:
    candidate = slugify(base)
    suffix = 1
    while True:
        result = await session.execute(select(Tenant.id).where(Tenant.slug == candidate))
        if not result.scalar_one_or_none():
            return candidate
        suffix += 1
        candidate = f"{slugify(base)[:55]}-{suffix}"


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    if settings.signup_mode not in {"open", "invite"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="signup disabled")
    existing = await session.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    user = User(
        email=payload.email.lower(),
        name=payload.name,
        password_hash=hash_password(payload.password),
        email_verified=settings.auto_verify_email,
    )
    session.add(user)
    await session.flush()
    tenant = Tenant(
        name=payload.tenant_name or payload.name or payload.email.split("@")[0],
        slug=await _unique_slug(session, payload.tenant_name or payload.email.split("@")[0]),
        created_by=user.id,
        settings={},
    )
    session.add(tenant)
    await session.flush()
    session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
    raw_token = None
    if not settings.auto_verify_email:
        raw_token, token_hash = new_email_token()
        session.add(
            EmailToken(
                user_id=user.id,
                kind="verify_email",
                token_hash=token_hash,
                expires_at=utcnow() + timedelta(hours=settings.email_token_hours),
            )
        )
    await audit(
        session,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="auth.register",
        resource_type="user",
        resource_id=user.id,
        **audit_context(request),
    )
    await session.commit()
    if not settings.auto_verify_email:
        verify_url = f"{settings.public_base_url}/verify?token={raw_token}"
        background_tasks.add_task(
            send_email,
            user.email,
            "Verify your FlowMind account",
            f"Welcome to FlowMind. Verify your email: {verify_url}",
        )
        if not settings.debug:
            raw_token = None
    data = await _auth_response(session, user, response, verification_token=raw_token)
    await session.commit()
    return data


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email not verified")
    response_data = await _auth_response(session, user, response)
    await session.commit()
    return response_data


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing refresh token")
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw), RefreshToken.revoked_at.is_(None)
        )
    )
    token = result.scalar_one_or_none()
    if not token or is_expired(token.expires_at):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")
    token.revoked_at = utcnow()
    user = await session.get(User, token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user disabled")
    data = await _auth_response(session, user, response)
    await session.commit()
    return data


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Response:
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
        )
        token = result.scalar_one_or_none()
        if token:
            token.revoked_at = utcnow()
            await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    pairs = await _memberships(session, user.id)
    return {
        "user": UserOut.model_validate(user),
        "tenants": [_tenant_out(pair[0]) for pair in pairs],
        "active_tenant_id": principal.tenant_id,
        "role": principal.role,
    }


@router.post("/switch-tenant", response_model=AuthResponse)
async def switch_tenant(
    tenant_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    membership = await session.execute(
        select(Membership).where(
            Membership.user_id == user.id, Membership.tenant_id == tenant_id
        )
    )
    if not membership.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a member")
    data = await _auth_response(session, user, response)
    await session.commit()
    return data


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    result = await session.execute(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(payload.token),
            EmailToken.kind == "verify_email",
            EmailToken.used_at.is_(None),
        )
    )
    token = result.scalar_one_or_none()
    if not token or is_expired(token.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired token")
    user = await session.get(User, token.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    user.email_verified = True
    token.used_at = utcnow()
    await session.commit()
    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user:
        raw, token_hash = new_email_token()
        session.add(
            EmailToken(
                user_id=user.id,
                kind="reset_password",
                token_hash=token_hash,
                expires_at=utcnow() + timedelta(hours=settings.password_reset_hours),
            )
        )
        await session.commit()
        background_tasks.add_task(
            send_email,
            user.email,
            "Reset your FlowMind password",
            f"Reset link: {settings.public_base_url}/reset?token={raw}",
        )
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    result = await session.execute(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(payload.token),
            EmailToken.kind == "reset_password",
            EmailToken.used_at.is_(None),
        )
    )
    token = result.scalar_one_or_none()
    if not token or is_expired(token.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired token")
    user = await session.get(User, token.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    user.password_hash = hash_password(payload.password)
    token.used_at = utcnow()
    await session.commit()
    return {"ok": True}


@router.post("/accept-invite")
async def accept_invite(
    payload: AcceptInviteRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    result = await session.execute(
        select(Invitation).where(
            Invitation.token_hash == hash_token(payload.token), Invitation.accepted_at.is_(None)
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation or is_expired(invitation.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid invitation")
    user_result = await session.execute(select(User).where(User.email == invitation.email))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(
            email=invitation.email,
            name=payload.name or invitation.email.split("@")[0],
            password_hash=hash_password(payload.password),
            email_verified=True,
        )
        session.add(user)
        await session.flush()
    session.add(Membership(tenant_id=invitation.tenant_id, user_id=user.id, role=invitation.role))
    invitation.accepted_at = utcnow()
    data = await _auth_response(session, user, response)
    await session.commit()
    return data


