from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import (
    agent_sessions,
    approvals,
    auth,
    health,
    hooks,
    knowledge,
    mcp_demo,
    oauth,
    plugins,
    resources,
    runs,
    tenants,
    workflows,
)
from app.config import settings
from app.db import init_db

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        await init_db()
    if settings.seed_demo:
        try:
            from scripts.seed import seed

            await seed(init=False)
        except Exception:
            logger.exception("demo seed failed")
    try:
        from app.services.dispatch import recover_interrupted_ingestions

        recovered = await recover_interrupted_ingestions()
        if recovered:
            logger.warning("marked %s interrupted document ingestions as failed", recovered)
    except Exception:
        logger.exception("failed to recover interrupted document ingestions")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "internal server error",
                "details": {} if not settings.debug else {"type": type(exc).__name__, "message": str(exc)},
                "request_id": request_id,
            }
        },
    )


for router in [
    auth.router,
    tenants.router,
    workflows.router,
    runs.router,
    approvals.router,
    agent_sessions.router,
    oauth.router,
    plugins.router,
    resources.router,
    knowledge.router,
    mcp_demo.router,
    hooks.router,
    health.router,
]:
    app.include_router(router)


dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = dist / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


@app.get("/")
async def root() -> dict:
    return {"name": settings.app_name, "version": "0.1.0", "docs": "/docs"}
