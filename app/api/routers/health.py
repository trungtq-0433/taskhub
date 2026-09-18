"""Liveness and readiness endpoints."""

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionDep
from app.core.exceptions import ServiceUnavailableError
from app.schemas.base import BaseSchema

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
async def ready(session: SessionDep) -> ReadinessStatus:
    """Readiness: the process can reach its database."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("The database is not reachable.") from exc

    return ReadinessStatus(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        database="ok",
    )
