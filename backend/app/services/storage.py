from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from minio import Minio

from app.config import settings


class StorageError(Exception):
    pass


def _client() -> Minio | None:
    if not settings.minio_endpoint:
        return None
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket() -> None:
    client = _client()
    if not client:
        return
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


def _local_path(key: str) -> Path:
    root = Path(settings.local_storage_dir).resolve()
    target = (root / key).resolve()
    if root not in target.parents and target != root:
        raise StorageError("invalid storage key")
    return target


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client = _client()
    if client:
        try:
            ensure_bucket()
            client.put_object(
                settings.minio_bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return
        except Exception:
            pass
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get_bytes(key: str) -> bytes:
    client = _client()
    if client:
        try:
            response = client.get_object(settings.minio_bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception:
            pass
    path = _local_path(key)
    if not path.exists():
        raise StorageError(f"object not found: {key}")
    return path.read_bytes()


def delete_object(key: str) -> None:
    client = _client()
    if client:
        try:
            client.remove_object(settings.minio_bucket, key)
            return
        except Exception:
            pass
    path = _local_path(key)
    if path.exists():
        path.unlink()


def presigned_put_url(key: str, expires_seconds: int = 900) -> str | None:
    client = _client()
    if not client:
        return None
    try:
        ensure_bucket()
        from datetime import timedelta

        return client.presigned_put_object(
            settings.minio_bucket, key, expires=timedelta(seconds=expires_seconds)
        )
    except Exception:
        return None


def new_storage_key(tenant_id: str, kb_id: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()[:12]
    return f"{tenant_id}/{kb_id}/{uuid.uuid4().hex}{suffix}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_upload_dir() -> Path:
    path = Path(settings.local_storage_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path

