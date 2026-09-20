"""Readiness behaviour, including the path where the database is gone."""

from collections.abc import AsyncGenerator, Generator
from http import HTTPStatus

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import app
from app.schemas.problem import PROBLEM_MEDIA_TYPE

# A real engine pointed at a port nothing listens on. Connecting fails the way
# a dead database fails, without mocking the driver into pretending.
UNREACHABLE = "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nothing"


async def _dead_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(UNREACHABLE, poolclass=None)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def unreachable_database() -> Generator[None, None, None]:
    app.dependency_overrides[get_session] = _dead_session
    yield
    app.dependency_overrides.pop(get_session, None)


async def test_ready_reports_503_when_the_database_is_gone(unreachable_database: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/ready")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)

    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:service-unavailable"
    assert problem["detail"] == "The database is not reachable."


async def test_liveness_does_not_touch_the_database(unreachable_database: None) -> None:
    """/health must stay up when the database is down, or restarts cascade."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/health")

    assert response.status_code == HTTPStatus.OK
