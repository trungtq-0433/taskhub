"""Liveness and readiness endpoints."""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.base import BaseSchema
from app.services.health import HealthServiceDep

router = APIRouter(tags=["health"])


class HealthStatus(BaseSchema):
    status: str
    version: str
    environment: str


class ReadinessStatus(HealthStatus):
    database: str


@router.get("/health")
async def health() -> HealthStatus:
    """Liveness: the process is up and serving."""
    return HealthStatus(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get("/ready")
async def ready(service: HealthServiceDep) -> ReadinessStatus:
    """Readiness: the process can reach its database."""
    await service.check_database()

    return ReadinessStatus(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        database="ok",
    )
