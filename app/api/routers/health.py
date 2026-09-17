"""Liveness and readiness endpoints."""

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionDep
from app.core.exceptions import ServiceUnavailableError
from app.schemas.base import BaseSchema, ResponseEnvelope

router = APIRouter(tags=["health"])


class HealthStatus(BaseSchema):
    status: str
    version: str
    environment: str


class ReadinessStatus(HealthStatus):
    database: str


@router.get("/health", response_model=ResponseEnvelope[HealthStatus])
async def health() -> ResponseEnvelope[HealthStatus]:
    """Liveness: the process is up and serving."""
    return ResponseEnvelope.of(
        HealthStatus(
            status="ok",
            version=settings.app_version,
            environment=settings.environment,
        )
    )


@router.get("/ready", response_model=ResponseEnvelope[ReadinessStatus])
async def ready(session: SessionDep) -> ResponseEnvelope[ReadinessStatus]:
    """Readiness: the process can reach its database."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("Database is not reachable.") from exc

    return ResponseEnvelope.of(
        ReadinessStatus(
            status="ok",
            version=settings.app_version,
            environment=settings.environment,
            database="ok",
        )
    )
