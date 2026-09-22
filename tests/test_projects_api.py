"""Project endpoints, end to end through the real app."""

from collections.abc import Callable
from http import HTTPStatus

from httpx import AsyncClient

from app.schemas.problem import PROBLEM_MEDIA_TYPE

BASE = "/api/v1/projects"


async def test_create_returns_201_and_the_resource(api_client: Callable[[], AsyncClient]) -> None:
    async with api_client() as client:
        response = await client.post(BASE, json={"name": "Ship v1"})

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["name"] == "Ship v1"
    assert body["status"] == "active"
    assert body["id"]
    assert body["created_at"]


async def test_round_trip(api_client: Callable[[], AsyncClient]) -> None:
    async with api_client() as client:
        created = (await client.post(BASE, json={"name": "Round trip"})).json()

        fetched = await client.get(f"{BASE}/{created['id']}")
        assert fetched.status_code == HTTPStatus.OK
        assert fetched.json() == created

        listed = (await client.get(BASE)).json()
        assert listed["total"] == 1
        assert listed["items"][0]["name"] == "Round trip"

        deleted = await client.delete(f"{BASE}/{created['id']}")
        assert deleted.status_code == HTTPStatus.NO_CONTENT
        assert deleted.content == b"", "204 must carry no body"

        assert (await client.get(f"{BASE}/{created['id']}")).status_code == HTTPStatus.NOT_FOUND


async def test_patch_leaves_unmentioned_fields_alone(
    api_client: Callable[[], AsyncClient],
) -> None:
    """The bug this guards against nulls every column the client omitted."""
    async with api_client() as client:
        created = (
            await client.post(BASE, json={"name": "Keep me", "description": "Do not lose this"})
        ).json()

        patched = await client.patch(f"{BASE}/{created['id']}", json={"status": "archived"})

    assert patched.status_code == HTTPStatus.OK
    body = patched.json()
    assert body["status"] == "archived"
    assert body["description"] == "Do not lose this"
    assert body["name"] == "Keep me"


async def test_missing_project_is_a_specific_problem(
    api_client: Callable[[], AsyncClient],
) -> None:
    async with api_client() as client:
        response = await client.get(f"{BASE}/999")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:project-not-found"
    assert "999" in problem["detail"]


async def test_duplicate_name_is_a_conflict(api_client: Callable[[], AsyncClient]) -> None:
    async with api_client() as client:
        await client.post(BASE, json={"name": "Only one"})
        response = await client.post(BASE, json={"name": "Only one"})

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"] == "urn:taskhub:problem:duplicate-project-name"


async def test_renaming_to_its_own_name_is_allowed(api_client: Callable[[], AsyncClient]) -> None:
    """The self-clash case: the row must not conflict with itself."""
    async with api_client() as client:
        created = (await client.post(BASE, json={"name": "Same"})).json()
        response = await client.patch(f"{BASE}/{created['id']}", json={"name": "Same"})

    assert response.status_code == HTTPStatus.OK


async def test_invalid_payload_lists_the_field(api_client: Callable[[], AsyncClient]) -> None:
    async with api_client() as client:
        response = await client.post(BASE, json={"name": ""})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:validation"
    assert problem["errors"][0]["field"] == "name"


async def test_pagination_reports_the_full_total(api_client: Callable[[], AsyncClient]) -> None:
    async with api_client() as client:
        for i in range(5):
            await client.post(BASE, json={"name": f"Project {i}"})

        page = (await client.get(BASE, params={"page": 2, "size": 2})).json()

    assert page["total"] == 5
    assert page["pages"] == 3
    assert page["page"] == 2
    assert len(page["items"]) == 2


async def test_openapi_documents_the_not_found_response() -> None:
    from httpx import ASGITransport

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        schema = (await client.get("/openapi.json")).json()

    detail_route = schema["paths"]["/api/v1/projects/{project_id}"]["get"]["responses"]
    assert "404" in detail_route, "a client cannot handle what the schema never mentions"


async def test_page_is_bounded_like_size(api_client: Callable[[], AsyncClient]) -> None:
    """An unbounded page overflows the bigint OFFSET and dies as a 500."""
    async with api_client() as client:
        response = await client.get(BASE, params={"page": 999_999_999_999_999_999})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "page"
