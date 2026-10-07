"""Shared pytest fixtures."""

from collections.abc import AsyncGenerator, Callable, Coroutine, Iterator
from typing import Any, Protocol

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.permissions import AdminDep, ProjectManagerDep
from app.core.config import settings
from app.core.database import get_session
from app.core.handlers import register_exception_handlers
from app.main import app
from tests.db import (
    assert_not_the_dev_database,
    create_database_if_absent,
    database_url_for_tests,
    migrate,
    wipe_committed_rows,
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


@pytest.fixture(scope="session", autouse=True)
def _suite_ignores_outside_services() -> Iterator[None]:
    """Keep the developer's `.env` from reaching real services during a run.
    `SMTP_HOST` would make every comment test send real mail, `REDIS_URL` would
    carry one test's rolled-back tags into the next. Tests opt in through
    `app.dependency_overrides` (`get_mailer`, `get_tag_list_cache`).
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "smtp_host", None)
        patch.setattr(settings, "redis_url", None)
        yield


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
async def committing_sessions(
    _engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Real sessions that really commit, with the tables emptied around the test.

    Built like production (`app/core/database.py`): `autoflush=False`, so the
    tests run in the flush mode the code ships with and a missing explicit
    `flush()` fails here rather than in prod. Wiped before `yield` as well as
    after, so rows left by a killed run cannot poison the next one.
    """
    factory = async_sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    await wipe_committed_rows(factory)
    yield factory
    await wipe_committed_rows(factory)


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


def _build_permission_test_app(db_session: AsyncSession) -> FastAPI:
    """A throwaway `FastAPI` instance for exercising `AdminDep`/`ProjectManagerDep`.

    Neither `client` nor `route_client` fits: `route_client` does not override
    `get_session`, so a route mounted there would run against the real
    database, and mounting on the shared `app` at all would invalidate its
    cached OpenAPI schema for every other test in the suite. This app exists
    only for the duration of one test — its own exception handlers, so a
    `ForbiddenError`/`NotFoundError` renders the same problem+json body the
    real app would, and its own `get_session` override pointed at the test's
    `db_session`.
    """
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/admin-only")
    async def admin_only(user: AdminDep) -> dict[str, int]:
        return {"user_id": user.id}

    @test_app.get("/projects/{project_id}/manager-only")
    async def manager_only(user: ProjectManagerDep) -> dict[str, int]:
        return {"user_id": user.id}

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    test_app.dependency_overrides[get_session] = _override_session
    return test_app


@pytest.fixture
async def permission_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """An `AsyncClient` bound to the throwaway app above, sharing the test's
    transaction so rows it creates roll back like every other test's."""
    transport = ASGITransport(app=_build_permission_test_app(db_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
