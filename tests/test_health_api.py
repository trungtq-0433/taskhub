"""`GET /health`: the liveness probe the image's HEALTHCHECK calls."""

from httpx import AsyncClient

from app.core.middleware import REQUEST_ID_HEADER
from app.main import app


async def test_health_answers_ok_with_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert REQUEST_ID_HEADER.lower() in response.headers


def test_health_is_not_in_the_openapi_document() -> None:
    assert "/health" not in app.openapi()["paths"]
