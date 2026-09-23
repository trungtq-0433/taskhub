"""How the application is assembled, as opposed to how it answers.

These build their own app rather than using the shared one, because what they
check is what `create_app()` decides at construction — and the shared instance
was built once, under the test environment.
"""

from http import HTTPStatus

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import create_app

DOC_ROUTES = ["/docs", "/redoc", "/openapi.json"]


def _app_for(environment: str) -> FastAPI:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "environment", environment)
        return create_app()


@pytest.mark.parametrize("environment", ["local", "test", "staging"])
async def test_api_docs_are_served_outside_production(environment: str) -> None:
    app = _app_for(environment)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for route in DOC_ROUTES:
            assert (await client.get(route)).status_code == HTTPStatus.OK, route


async def test_api_docs_are_closed_in_production() -> None:
    """Unauthenticated docs hand an attacker the whole API surface.

    `openapi_url` matters as much as `/docs`: hiding only the UI leaves the
    schema it renders available to anyone who asks for it.
    """
    app = _app_for("production")

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for route in DOC_ROUTES:
            response = await client.get(route)
            assert response.status_code == HTTPStatus.NOT_FOUND, route
            # Still a problem document — the handlers apply to these paths too.
            assert response.json()["type"] == "urn:taskhub:problem:not-found"


async def test_the_api_itself_still_works_in_production() -> None:
    """Closing the docs must not close the API."""
    app = _app_for("production")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/projects", params={"page": 0})

    # 422 rather than 404: the route exists and rejected the payload.
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
