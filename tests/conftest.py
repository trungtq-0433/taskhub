"""Shared pytest fixtures."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.core.config import settings
from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def api_prefix() -> str:
    return settings.api_prefix


@pytest.fixture
def route_client() -> Callable[..., Awaitable[Response]]:
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
