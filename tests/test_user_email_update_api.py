"""`email` on `PUT /users/me`: absent keeps, `null` clears, a value sets.

`full_name` keeps the replace semantics of the rest of this route (decision
13 in the testing plan) — only `email` is allowed to be omitted.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.user import UserRepository
from tests.factories import auth_headers, make_user

ME_URL = "/api/v1/users/me"


async def _seed(session: AsyncSession, *, email: str | None) -> tuple[User, User]:
    me = make_user("me", full_name="Me", email=email)
    other = make_user("other", email="other@example.com")
    session.add_all([me, other])
    await session.flush()
    return me, other


async def _stored_email(session: AsyncSession, username: str) -> str | None:
    session.expire_all()
    return await session.scalar(select(User.email).where(User.username == username))


async def test_put_me_without_the_email_key_keeps_it(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    me, _ = await _seed(db_session, email="me@example.com")

    response = await api_client.put(ME_URL, json={"full_name": "Renamed"}, headers=auth_headers(me))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["full_name"] == "Renamed"
    assert response.json()["email"] == "me@example.com"


async def test_put_me_with_null_email_clears_it(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    me, _ = await _seed(db_session, email="me@example.com")

    response = await api_client.put(
        ME_URL, json={"full_name": "Me", "email": None}, headers=auth_headers(me)
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["email"] is None
    assert await _stored_email(db_session, "me") is None


async def test_put_me_sets_a_new_email_lowercase(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    me, _ = await _seed(db_session, email=None)

    response = await api_client.put(
        ME_URL, json={"full_name": "Me", "email": "New.Me@Example.COM"}, headers=auth_headers(me)
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["email"] == "new.me@example.com"
    assert await _stored_email(db_session, "me") == "new.me@example.com"


async def test_put_me_to_another_users_email_is_409_and_changes_nothing(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    me, _ = await _seed(db_session, email="me@example.com")

    response = await api_client.put(
        ME_URL,
        json={"full_name": "Renamed", "email": "OTHER@example.com"},
        headers=auth_headers(me),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("email-taken")
    assert await _stored_email(db_session, "me") == "me@example.com"


async def test_put_me_with_its_own_current_email_is_200(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    me, _ = await _seed(db_session, email="me@example.com")

    response = await api_client.put(
        ME_URL, json={"full_name": "Me", "email": "Me@Example.com"}, headers=auth_headers(me)
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["email"] == "me@example.com"


async def test_a_lost_email_race_on_put_me_answers_409_email_taken(
    db_session: AsyncSession, api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-check is fooled into seeing a free address; the unique index
    still refuses it at commit and the route must answer `email-taken`."""
    me, _ = await _seed(db_session, email=None)

    async def fake_get_by_email(self: UserRepository, email: str) -> User | None:
        return None

    monkeypatch.setattr(UserRepository, "get_by_email", fake_get_by_email)

    response = await api_client.put(
        ME_URL, json={"full_name": "Me", "email": "other@example.com"}, headers=auth_headers(me)
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("email-taken")


async def test_put_me_with_only_an_email_still_requires_full_name_422(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    me, _ = await _seed(db_session, email=None)

    response = await api_client.put(
        ME_URL, json={"email": "me@example.com"}, headers=auth_headers(me)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
