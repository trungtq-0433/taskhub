"""Project endpoints, end to end through the real app."""

from http import HTTPStatus

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.problem import PROBLEM_MEDIA_TYPE

BASE = "/api/v1/projects"


async def test_create_returns_201_and_the_resource(api_client: AsyncClient) -> None:
    response = await api_client.post(BASE, json={"name": "Ship v1"})

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["name"] == "Ship v1"
    assert body["status"] == "active"
    assert body["id"]
    assert body["created_at"]


async def test_round_trip(api_client: AsyncClient) -> None:
    created = (await api_client.post(BASE, json={"name": "Round trip"})).json()

    fetched = await api_client.get(f"{BASE}/{created['id']}")
    assert fetched.status_code == HTTPStatus.OK
    # The detail route answers ProjectDetail while POST still answers
    # ProjectRead, so the two are equal on every field the create returned
    # plus the one the detail adds.
    assert fetched.json() == created | {"total_tasks": 0}

    listed = (await api_client.get(BASE)).json()
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "Round trip"

    deleted = await api_client.delete(f"{BASE}/{created['id']}")
    assert deleted.status_code == HTTPStatus.NO_CONTENT
    assert deleted.content == b"", "204 must carry no body"

    assert (await api_client.get(f"{BASE}/{created['id']}")).status_code == HTTPStatus.NOT_FOUND


async def test_patch_leaves_unmentioned_fields_alone(api_client: AsyncClient) -> None:
    """The bug this guards against nulls every column the client omitted."""
    created = (
        await api_client.post(BASE, json={"name": "Keep me", "description": "Do not lose this"})
    ).json()

    patched = await api_client.patch(f"{BASE}/{created['id']}", json={"status": "archived"})

    assert patched.status_code == HTTPStatus.OK
    body = patched.json()
    assert body["status"] == "archived"
    assert body["description"] == "Do not lose this"
    assert body["name"] == "Keep me"


async def test_missing_project_is_a_specific_problem(api_client: AsyncClient) -> None:
    response = await api_client.get(f"{BASE}/999")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:project-not-found"
    assert "999" in problem["detail"]


async def test_duplicate_name_is_a_conflict(api_client: AsyncClient) -> None:
    await api_client.post(BASE, json={"name": "Only one"})
    response = await api_client.post(BASE, json={"name": "Only one"})

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"] == "urn:taskhub:problem:duplicate-project-name"


async def test_renaming_to_its_own_name_is_allowed(api_client: AsyncClient) -> None:
    """The self-clash case: the row must not conflict with itself."""
    created = (await api_client.post(BASE, json={"name": "Same"})).json()
    response = await api_client.patch(f"{BASE}/{created['id']}", json={"name": "Same"})

    assert response.status_code == HTTPStatus.OK


async def test_invalid_payload_lists_the_field(api_client: AsyncClient) -> None:
    response = await api_client.post(BASE, json={"name": ""})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:validation"
    assert problem["errors"][0]["field"] == "name"


async def test_pagination_reports_the_full_total(api_client: AsyncClient) -> None:
    for i in range(5):
        await api_client.post(BASE, json={"name": f"Project {i}"})

    page = (await api_client.get(BASE, params={"page": 2, "size": 2})).json()

    assert page["total"] == 5
    assert page["pages"] == 3
    assert page["page"] == 2
    assert len(page["items"]) == 2


async def test_openapi_documents_the_not_found_response() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        schema = (await client.get("/openapi.json")).json()

    detail_route = schema["paths"]["/api/v1/projects/{project_id}"]["get"]["responses"]
    assert "404" in detail_route, "a client cannot handle what the schema never mentions"


async def test_page_is_bounded_like_size(api_client: AsyncClient) -> None:
    """An unbounded page overflows the bigint OFFSET and dies as a 500."""
    response = await api_client.get(BASE, params={"page": 999_999_999_999_999_999})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "page"


async def test_explicit_null_on_a_required_field_is_a_validation_error(
    api_client: AsyncClient,
) -> None:
    """`{"name": null}` is the client sending something wrong, not a conflict.

    Omitting a field means "leave it alone"; sending null means "set it to
    null", which a NOT NULL column refuses. Answering 409 tells the client
    someone else changed the row and retrying might help — it will not.
    """
    created = (await api_client.post(BASE, json={"name": "Keep"})).json()

    response = await api_client.patch(f"{BASE}/{created['id']}", json={"name": None})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    problem = response.json()
    assert problem["type"] == "urn:taskhub:problem:validation"
    assert problem["errors"][0]["field"] == "name"


async def test_explicit_null_on_a_nullable_field_still_clears_it(
    api_client: AsyncClient,
) -> None:
    """The mirror case: description IS nullable, so null must keep working."""
    created = (
        await api_client.post(BASE, json={"name": "Clearable", "description": "gone soon"})
    ).json()

    response = await api_client.patch(f"{BASE}/{created['id']}", json={"description": None})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["description"] is None


async def test_openapi_declares_the_problem_media_type_for_every_error(
    api_client: AsyncClient,
) -> None:
    """A schema that says application/json for 404 misdescribes every failure."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        schema = (await client.get("/openapi.json")).json()

    detail = schema["paths"]["/api/v1/projects/{project_id}"]["get"]["responses"]
    create = schema["paths"]["/api/v1/projects"]["post"]["responses"]

    assert list(detail["404"]["content"]) == [PROBLEM_MEDIA_TYPE]
    assert list(create["409"]["content"]) == [PROBLEM_MEDIA_TYPE]


async def test_patch_refuses_an_empty_name(api_client: AsyncClient) -> None:
    """NOT NULL lets `''` through, so validation is the only thing stopping it."""
    created = (await api_client.post(BASE, json={"name": "Named"})).json()

    response = await api_client.patch(f"{BASE}/{created['id']}", json={"name": ""})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "name"
