from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FlowMind"
    environment: str = "development"
    debug: bool = True
    secret_key: str = "dev-secret-change-me"
    app_encryption_key: str = ""
    public_base_url: str = "http://localhost:8020"
    web_base_url: str = ""
    signup_mode: str = "open"
    seed_demo: bool = True
    auto_verify_email: bool = True

    database_url: str = "sqlite+aiosqlite:///./flowmind.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    run_inline: bool = True
    auto_create_tables: bool = True

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    email_token_hours: int = 24
    password_reset_hours: int = 1

    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@flowmind.local"
    smtp_tls: bool = False

    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "flowmind"
    minio_secure: bool = False
    local_storage_dir: str = "./data/uploads"

    runner_url: str = "http://localhost:9100"
    runner_hmac_secret: str = "change-runner-secret"

    default_chat_base_url: str = "http://localhost:11434/v1"
    default_chat_api_key: str = ""
    default_chat_model: str = "qwen2.5:7b"
    default_embedding_base_url: str = "http://localhost:11434/v1"
    default_embedding_api_key: str = ""
    default_embedding_model: str = "bge-m3"
    default_embedding_dimension: int = 1024

    otel_exporter_otlp_endpoint: str = ""
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    run_retention_days: int = 90
    audit_retention_days: int = 365
    max_workflow_nodes: int = 200
    max_run_seconds: int = 86_400
    default_run_seconds: int = 1_800
    max_parallel_nodes: int = 4
    runner_timeout_seconds: int = 30
    runner_memory_mb: int = 256
    max_upload_bytes: int = 50 * 1024 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def encryption_key(self) -> bytes:
        if self.app_encryption_key:
            raw = self.app_encryption_key.encode()
            try:
                decoded = base64.urlsafe_b64decode(raw)
                if len(decoded) == 32:
                    return decoded
            except Exception:
                pass
            return hashlib.sha256(raw).digest()
        return hashlib.sha256(self.secret_key.encode()).digest()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
