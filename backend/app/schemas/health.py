"""Response schemas for the health and service-metadata endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    """Result of a real round trip to MongoDB."""

    status: Literal["connected", "unavailable"]
    database: str = Field(description="Name of the application database.")
    latency_ms: float | None = Field(
        default=None, description="Measured round-trip time of the ping command."
    )
    server_version: str | None = Field(
        default=None, description="MongoDB server version, when reachable."
    )
    error: str | None = Field(
        default=None, description="Why the connection failed, when it did."
    )


class HealthResponse(BaseModel):
    """Overall service health. Returns HTTP 503 when the database is down."""

    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    timestamp: datetime
    database: DatabaseHealth


class LivenessResponse(BaseModel):
    """Process liveness only. Never touches MongoDB."""

    status: Literal["alive"]
    service: str
    timestamp: datetime


class ServiceInfoResponse(BaseModel):
    """Root endpoint: what this service is and where to read its API."""

    service: str
    version: str
    environment: str
    docs: str
    health: str
