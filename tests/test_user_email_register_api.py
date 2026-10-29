"""`email` on `POST /users/register`, and where an address may — and may not — appear.

The address is the caller's own business: it comes back on the register
response and `GET /users/me` (`UserPrivate`) and nowhere else. The last two
tests are the ones that matter for that — the public profile and a task's
nested assignee are built from `UserRead`/`UserSummary`, which must never
grow an `email` key.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User
from app.repositories.user import UserRepository
from tests.factories import auth_headers, make_user

REGISTER_URL = "/api/v1/users/register"
ME_URL = "/api/v1/users/me"


def _body(username: str = "trung", **extra: object) -> dict[str, object]:
    return {"username": username, "password": "correct-horse-battery", **extra}


async def test_register_with_an_email_stores_it_lowercase_and_returns_it(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    response = await api_client.post(REGISTER_URL, json=_body(email="Trung.Tran@Example.COM"))

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["email"] == "trung.tran@example.com"
    stored = await db_session.scalar(select(User.email).where(User.username == "trung"))
    assert stored == "trung.tran@example.com"


async def test_register_without_an_email_returns_null(api_client: AsyncClient) -> None:
    response = await api_client.post(REGISTER_URL, json=_body())

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["email"] is None


@pytest.mark.parametrize("email", ["not-an-email", "trung@"])
async def test_a_malformed_email_is_422_validation(api_client: AsyncClient, email: str) -> None:
    response = await api_client.post(REGISTER_URL, json=_body(email=email))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


async def test_an_email_already_registered_in_another_case_is_409_email_taken(
    api_client: AsyncClient,
) -> None:
    await api_client.post(REGISTER_URL, json=_body("first", email="Shared@example.com"))

    response = await api_client.post(REGISTER_URL, json=_body("second", email="SHARED@EXAMPLE.COM"))

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("email-taken")


async def test_with_username_and_email_both_taken_the_username_is_reported(
    api_client: AsyncClient,
) -> None:
    await api_client.post(REGISTER_URL, json=_body("first", email="shared@example.com"))

    response = await api_client.post(REGISTER_URL, json=_body("first", email="shared@example.com"))

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("username-taken")


async def test_a_lost_email_race_against_the_pre_check_still_answers_409_email_taken(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both requests pass `get_by_email` before either commits; the unique
    index picks the loser, and the slug must name the index that fired, not
    default to `username-taken`."""
    await api_client.post(REGISTER_URL, json=_body("first", email="shared@example.com"))

    async def fake_get_by_email(self: UserRepository, email: str) -> User | None:
        return None

    monkeypatch.setattr(UserRepository, "get_by_email", fake_get_by_email)

    response = await api_client.post(REGISTER_URL, json=_body("second", email="shared@example.com"))

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("email-taken")


async def test_an_email_longer_than_the_column_is_422_not_500(api_client: AsyncClient) -> None:
    # 64 + 1 + three 63-char labels + ".com": each part is legal alone, the
    # whole (260 characters) exceeds RFC 5321's 254.
    email = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 63}.com"
    assert len(email) > 254

    response = await api_client.post(REGISTER_URL, json=_body(email=email))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


async def test_get_me_returns_the_email(db_session: AsyncSession, api_client: AsyncClient) -> None:
    user = make_user("trung", email="trung@example.com")
    db_session.add(user)
    await db_session.flush()

    response = await api_client.get(ME_URL, headers=auth_headers(user))

    assert response.json()["email"] == "trung@example.com"


async def test_the_public_profile_never_shows_an_email(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    db_session.add(make_user("trung", email="trung@example.com"))
    await db_session.flush()

    body = (await api_client.get("/api/v1/users/trung/profile")).json()

    assert body["user"]["username"] == "trung"
    assert "email" not in body["user"]


async def test_a_task_assignee_never_shows_an_email(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    user = make_user("worker", email="worker@example.com")
    project = Project(name="Holder")
    db_session.add_all([user, project])
    await db_session.flush()
    created = await api_client.post(
        f"/api/v1/projects/{project.id}/tasks", json={"title": "T", "assignee_id": user.id}
    )
    assert created.status_code == HTTPStatus.CREATED

    items = (await api_client.get("/api/v1/tasks")).json()["items"]

    assert items[0]["assignee"]["username"] == "worker"
    assert "email" not in items[0]["assignee"]
