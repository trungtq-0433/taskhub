"""The response contract: plain models on success, RFC 9457 problems on failure."""

from http import HTTPStatus

import pytest
from fastapi import HTTPException, Query
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.main import app, create_app
from app.schemas.base import Page
from app.schemas.problem import PROBLEM_MEDIA_TYPE
from tests.conftest import RouteClient


async def test_success_response_is_the_model_itself(client: AsyncClient, api_prefix: str) -> None:
    response = await client.get(f"{api_prefix}/health")

    assert response.status_code == HTTPStatus.OK
    assert response.headers["content-type"].startswith("application/json")
    # No envelope: the model is the body.
    assert response.json() == {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
    }


def test_page_computes_its_page_count() -> None:
    page = Page.of([1, 2, 3], total=7, page=2, size=3)

    assert page.pages == 3
    assert page.model_dump() == {"items": [1, 2, 3], "total": 7, "page": 2, "size": 3, "pages": 3}


async def test_unknown_route_returns_a_problem_document(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)

    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:not-found"
    assert problem["title"] == "Not Found"
    assert problem["status"] == 404
    assert problem["instance"] == "/does-not-exist"
    # `detail` describes the occurrence; a copy of the title is not that.
    assert "detail" not in problem


async def test_domain_error_carries_its_own_type_and_status(route_client: RouteClient) -> None:
    async def raise_conflict() -> None:
        raise ConflictError("Email already registered.", problem_type="duplicate-email")

    response = await route_client("/_test/conflict", raise_conflict)

    assert response.status_code == HTTPStatus.CONFLICT
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:duplicate-email"
    assert problem["title"] == "Conflict"
    assert problem["detail"] == "Email already registered."


async def test_validation_failure_lists_offending_fields(route_client: RouteClient) -> None:
    async def needs_int(amount: int = Query()) -> dict[str, int]:
        return {"amount": amount}

    response = await route_client("/_test/validate", needs_int, params={"amount": "nan"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:validation"
    assert problem["errors"][0]["field"] == "amount"
    assert problem["errors"][0]["type"]


async def test_raw_http_exception_becomes_a_problem(route_client: RouteClient) -> None:
    async def raise_forbidden() -> None:
        raise HTTPException(status_code=403, detail="Not your project.")

    response = await route_client("/_test/forbidden", raise_forbidden)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:forbidden"
    assert problem["detail"] == "Not your project."
    assert problem["request_id"] == response.headers["x-request-id"]


async def test_absent_members_are_omitted(client: AsyncClient) -> None:
    """A problem with no field-level causes should not carry an empty `errors`."""
    problem = (await client.get("/does-not-exist")).json()

    assert "errors" not in problem


async def test_request_id_is_echoed_and_minted_per_request(
    client: AsyncClient, api_prefix: str
) -> None:
    first = await client.get(f"{api_prefix}/health")
    second = await client.get(f"{api_prefix}/health")

    assert first.headers["x-request-id"] != second.headers["x-request-id"]

    supplied = await client.get(f"{api_prefix}/health", headers={"X-Request-ID": "trace-abc"})
    assert supplied.headers["x-request-id"] == "trace-abc"


async def test_unhandled_exception_hides_internals() -> None:
    """With DEBUG off, a crash must answer with a problem and leak nothing.

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
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:internal-error"
    assert "leaked" not in problem["detail"]
    assert problem["request_id"]


async def test_openapi_documents_the_problem_document() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        schema = (await ac.get("/openapi.json")).json()

    health = schema["paths"]["/api/v1/health"]["get"]["responses"]

    # Success is documented as the bare model, not an envelope.
    ok_schema = health["200"]["content"]["application/json"]["schema"]
    assert ok_schema["$ref"].endswith("/HealthStatus")

    # And 422 is the problem document, with the right media type — FastAPI
    # would otherwise advertise its own HTTPValidationError here.
    assert PROBLEM_MEDIA_TYPE in health["422"]["content"]
    problem_schema = health["422"]["content"][PROBLEM_MEDIA_TYPE]["schema"]
    assert problem_schema["title"] == "ProblemDetail"
