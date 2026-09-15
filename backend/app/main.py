"""FastAPI application entry point.

Run it with::

    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

from the ``backend/`` directory, with the virtualenv active.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health as health_routes
from app.core.config import get_settings
from app.core.database import close_mongo_connection, connect_to_mongo
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

DESCRIPTION = """
Platform that runs real functional QA and real security tests against a
registered target application, normalises the evidence those tools produce,
and uses an LLM to explain, prioritise and recommend fixes for what the
evidence actually shows.

The AI never invents results. Every finding references evidence produced by
a tool that genuinely executed.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the MongoDB client and workspace directories for the process."""
    logger.info(
        "Starting %s v%s (environment=%s)",
        settings.project_name,
        settings.api_version,
        settings.environment,
    )
    await connect_to_mongo()

    settings.qa_workspace_root.mkdir(parents=True, exist_ok=True)
    settings.reports_root.mkdir(parents=True, exist_ok=True)
    logger.info("QA workspace root: %s", settings.qa_workspace_root)
    logger.info("CORS allow-list: %s", ", ".join(settings.cors_origins))

    yield

    await close_mongo_connection()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.project_name,
    version=settings.api_version,
    description=DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_routes.router)


@app.get("/", tags=["meta"], summary="Service metadata")
async def root() -> dict[str, str]:
    """Identify the service and point at its documentation."""
    return {
        "service": settings.project_name,
        "version": settings.api_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
    }
