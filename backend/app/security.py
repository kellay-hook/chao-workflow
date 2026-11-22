from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_password_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_fernet = Fernet(__import__("base64").urlsafe_b64encode(settings.encryption_key))


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _password_hasher.verify(hashed, password)
    except (VerifyMismatchError, Exception):
        return False


def needs_rehash(hashed: str) -> bool:
    return _password_hasher.check_needs_rehash(hashed)


def create_access_token(user_id: str, tenant_id: str, role: str) -> tuple[str, int]:
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("invalid or expired token") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise AuthError("invalid token type")
    return payload


def new_refresh_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw), datetime.now(UTC) + timedelta(days=settings.refresh_token_days)


def new_email_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def new_api_key() -> tuple[str, str, str]:
    raw = "wfk_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def encrypt_secret(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise AuthError("could not decrypt secret") from exc


def constant_time_equals(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)
