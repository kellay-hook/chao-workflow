from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Secret
from app.security import decrypt_secret, encrypt_secret


async def get_secret_value(session: AsyncSession, tenant_id: str, name: str) -> str | None:
    result = await session.execute(
        select(Secret).where(Secret.tenant_id == tenant_id, Secret.name == name)
    )
    secret = result.scalar_one_or_none()
    if not secret:
        return None
    return decrypt_secret(secret.ciphertext)


async def resolve_secret_refs(
    session: AsyncSession, tenant_id: str, value: object
) -> object:
    if isinstance(value, str):
        if value.startswith("${secret:") and value.endswith("}"):
            name = value[len("${secret:") : -1]
            resolved = await get_secret_value(session, tenant_id, name)
            if resolved is None:
                raise KeyError(f"secret {name} not found")
            return resolved
        return value
    if isinstance(value, dict):
        return {key: await resolve_secret_refs(session, tenant_id, item) for key, item in value.items()}
    if isinstance(value, list):
        return [await resolve_secret_refs(session, tenant_id, item) for item in value]
    return value


async def upsert_secret(
    session: AsyncSession, tenant_id: str, name: str, value: str, actor_id: str | None
) -> Secret:
    result = await session.execute(
        select(Secret).where(Secret.tenant_id == tenant_id, Secret.name == name)
    )
    secret = result.scalar_one_or_none()
    if secret:
        secret.ciphertext = encrypt_secret(value)
        secret.created_by = actor_id or secret.created_by
    else:
        secret = Secret(
            tenant_id=tenant_id,
            name=name,
            ciphertext=encrypt_secret(value),
            created_by=actor_id,
        )
        session.add(secret)
    await session.flush()
    return secret

