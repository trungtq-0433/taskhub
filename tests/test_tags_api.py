"""Tag endpoints, end to end through the real app."""

from http import HTTPStatus

from httpx import AsyncClient

BASE = "/api/v1/tags"


async def test_round_trip(api_client: AsyncClient) -> None:
    created = await api_client.post(BASE, json={"name": "urgent", "color": "#ff0000"})
    assert created.status_code == HTTPStatus.CREATED
    tag = created.json()
    assert tag["color"] == "#ff0000"

    listed = (await api_client.get(BASE)).json()
    assert listed["total"] == 1

    patched = await api_client.patch(f"{BASE}/{tag['id']}", json={"color": "#00ff00"})
    assert patched.status_code == HTTPStatus.OK
    assert patched.json()["color"] == "#00ff00"
    assert patched.json()["name"] == "urgent", "an omitted field must survive"

    deleted = await api_client.delete(f"{BASE}/{tag['id']}")
    assert deleted.status_code == HTTPStatus.NO_CONTENT
    assert deleted.content == b""


async def test_missing_tag_has_its_own_problem_type(api_client: AsyncClient) -> None:
    response = await api_client.get(f"{BASE}/999")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"] == "urn:taskhub:problem:tag-not-found"


async def test_duplicate_name_is_a_conflict(api_client: AsyncClient) -> None:
    await api_client.post(BASE, json={"name": "same"})
    response = await api_client.post(BASE, json={"name": "same"})

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"] == "urn:taskhub:problem:duplicate-tag-name"


async def test_a_malformed_colour_is_rejected(api_client: AsyncClient) -> None:
    response = await api_client.post(BASE, json={"name": "bad", "color": "red"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "color"


async def test_page_size_is_bounded(api_client: AsyncClient) -> None:
    """An unbounded size lets one request ask for the whole table."""
    response = await api_client.get(BASE, params={"size": 500})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
