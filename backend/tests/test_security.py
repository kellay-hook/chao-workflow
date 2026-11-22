from __future__ import annotations

from app.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    new_api_key,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token, expires_in = create_access_token("user-1", "tenant-1", "editor")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["role"] == "editor"
    assert expires_in > 0


def test_secret_encryption_roundtrip():
    ciphertext = encrypt_secret("my-secret")
    assert ciphertext != "my-secret"
    assert decrypt_secret(ciphertext) == "my-secret"


def test_api_key_shape():
    raw, prefix, digest = new_api_key()
    assert raw.startswith("wfk_")
    assert raw.startswith(prefix)
    assert digest == hash_token(raw)
