"""The response contract: success envelope, error envelope, handler wiring."""

from http import HTTPStatus

import pytest
from fastapi import HTTPException, Query
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.main import app, create_app
from app.schemas.base import PaginatedEnvelope, ResponseEnvelope
from tests.conftest import RouteClient


async def test_health_returns_success_envelope(client: AsyncClient, api_prefix: str) -> None:
    response = await client.get(f"{api_prefix}/health")

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["data"]["status"] == "ok"
    # `meta` is dropped when empty rather than serialized as null.
    assert "meta" not in body


def test_meta_is_kept_when_it_carries_something() -> None:
    envelope = ResponseEnvelope.of({"id": 1}, generated_at="2026-09-17")

    assert envelope.model_dump() == {"data": {"id": 1}, "meta": {"generated_at": "2026-09-17"}}


def test_paginated_envelope_computes_total_pages() -> None:
    envelope = PaginatedEnvelope.of([1, 2, 3], page=2, per_page=3, total=7)

    assert envelope.meta.total_pages == 3
    assert envelope.meta.page == 2


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == HTTPStatus.NOT_FOUND
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] == []


async def test_domain_error_maps_to_its_status_and_code(route_client: RouteClient) -> None:
    async def raise_conflict() -> None:
        raise ConflictError("Email already registered.", code="duplicate_email")

    response = await route_client("/_test/conflict", raise_conflict)

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == "duplicate_email"


async def test_validation_error_lists_offending_fields(route_client: RouteClient) -> None:
    async def needs_int(amount: int = Query()) -> dict[str, int]:
        return {"amount": amount}

    response = await route_client("/_test/validate", needs_int, params={"amount": "nan"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "amount"
    assert error["details"][0]["type"]


async def test_raw_http_exception_is_reshaped_into_the_envelope(route_client: RouteClient) -> None:
    async def raise_teapot() -> None:
        raise HTTPException(status_code=403, detail="Not your project.")

    response = await route_client("/_test/forbidden", raise_teapot)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"] == {
        "code": "forbidden",
        "message": "Not your project.",
        "details": [],
        "request_id": response.headers["x-request-id"],
    }


async def test_request_id_is_echoed_and_minted_per_request(
    client: AsyncClient, api_prefix: str
) -> None:
    first = await client.get(f"{api_prefix}/health")
    second = await client.get(f"{api_prefix}/health")

    assert first.headers["x-request-id"] != second.headers["x-request-id"]

    supplied = await client.get(f"{api_prefix}/health", headers={"X-Request-ID": "trace-abc"})
    assert supplied.headers["x-request-id"] == "trace-abc"


async def test_unhandled_exception_hides_internals() -> None:
    """With DEBUG off, a crash must answer with the envelope and leak nothing.

    Built from a fresh app: Starlette short-circuits to an HTML traceback when
    `debug` is on, so the production path is only observable with it off.
    """

    async def explode() -> None:
        raise RuntimeError("connection string leaked here")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "debug", False)
        prod_app = create_app()
        prod_app.router.add_api_route("/_test/boom", explode, methods=["GET"])

        transport = ASGITransport(app=prod_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/_test/boom")

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "leaked" not in error["message"]
    assert error["request_id"]


async def test_openapi_documents_the_error_envelope_for_422() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        schema = (await ac.get("/openapi.json")).json()

    validation = schema["paths"]["/api/v1/health"]["get"]["responses"]["422"]
    ref = validation["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorEnvelope")
