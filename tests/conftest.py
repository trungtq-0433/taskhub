"""Shared pytest fixtures."""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, Protocol

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import get_session
from app.main import app
from tests.db import (
    assert_not_the_dev_database,
    create_database_if_absent,
    database_url_for_tests,
    migrate,
)


class RouteClient(Protocol):
    """Callable returned by the `route_client` fixture."""

    def __call__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        params: dict[str, Any] | None = None,
        raise_server_exceptions: bool = True,
    ) -> Coroutine[Any, Any, Response]: ...


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def route_client() -> RouteClient:
    """Mount a throwaway route on the real app and call it.

    Exercising the actual application is the point: handler registration and
    middleware order are part of what these tests are checking.
    """

    async def call(
        path: str,
        endpoint: Callable[..., Any],
        *,
        params: dict[str, Any] | None = None,
        raise_server_exceptions: bool = True,
    ) -> Response:
        app.router.add_api_route(path, endpoint, methods=["GET"])
        app.openapi_schema = None  # the new route invalidates the cached schema

        transport = ASGITransport(app=app, raise_app_exceptions=raise_server_exceptions)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get(path, params=params)

    return call


@pytest.fixture(scope="session")
async def _engine() -> AsyncGenerator[AsyncEngine, None]:
    """One engine for the whole run, against a freshly migrated test database."""
    url = database_url_for_tests()
    assert_not_the_dev_database(url)

    await create_database_if_absent(url)
    migrate(url)

    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """A session whose every write is undone when the test ends.

    The outer transaction on the connection is what gets rolled back.
    `join_transaction_mode="create_savepoint"` is load-bearing: the service
    layer calls `commit()`, and without it that commit would end the outer
    transaction and there would be nothing left to roll back. With it, the
    session's commit releases a SAVEPOINT instead and the outer transaction
    survives to be discarded.
    """
    async with _engine.connect() as connection:
        await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        async with factory() as session:
            yield session
        await connection.rollback()


@pytest.fixture
async def api_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client whose requests run inside the test's transaction.

    Without the override the request would open its own session, commit for
    real, and leave rows behind — a suite that passes once and then starts
    failing on duplicate keys.
    """

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)
