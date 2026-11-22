from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if settings.is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=10000")
        finally:
            cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401

    if not settings.is_sqlite:
        async with engine.begin() as conn:
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception:
                pass
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            except Exception:
                pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.is_sqlite:
            columns = await conn.execute(text("PRAGMA table_info(documents)"))
            names = {row[1] for row in columns.fetchall()}
            if "metadata_json" not in names:
                await conn.execute(text("ALTER TABLE documents ADD COLUMN metadata_json JSON DEFAULT '{}'"))
            oauth_columns = await conn.execute(text("PRAGMA table_info(oauth_connections)"))
            oauth_names = {row[1] for row in oauth_columns.fetchall()}
            if oauth_names and "token_auth_method" not in oauth_names:
                await conn.execute(
                    text(
                        "ALTER TABLE oauth_connections ADD COLUMN token_auth_method "
                        "VARCHAR(30) DEFAULT 'client_secret_post'"
                    )
                )
        else:
            await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb"))
            await conn.execute(
                text(
                    "ALTER TABLE oauth_connections ADD COLUMN IF NOT EXISTS token_auth_method "
                    "VARCHAR(30) DEFAULT 'client_secret_post'"
                )
            )

    if not settings.is_sqlite:
        async with engine.begin() as conn:
            try:
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
                        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
                    )
                )
            except Exception:
                pass
            try:
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_chunks_search_tsv "
                        "ON document_chunks USING gin (to_tsvector('simple', search_text))"
                    )
                )
            except Exception:
                pass
