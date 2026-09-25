"""Register, log in, and act as the current user — happy paths only.

The full validation and failure matrix (bad password, wrong credentials, a
tampered or expired token, ...) lands in phase 04. This file exists so each
of the four endpoints is proven to work at all, end to end, before that
breadth is added.
"""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

REGISTER_URL = "/api/v1/users/register"
LOGIN_URL = "/api/v1/users/login"
ME_URL = "/api/v1/users/me"


async def test_register_creates_a_user_and_returns_it(api_client: AsyncClient) -> None:
    response = await api_client.post(
        REGISTER_URL,
        json={"username": "Trung", "password": "correct-horse-battery", "full_name": "Trung"},
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["username"] == "trung", "the username is normalised before it is stored"
    assert body["full_name"] == "Trung"
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_rejects_a_username_already_taken(api_client: AsyncClient) -> None:
    payload = {"username": "trung", "password": "correct-horse-battery"}
    await api_client.post(REGISTER_URL, json=payload)

    response = await api_client.post(REGISTER_URL, json=payload)

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("username-taken")


async def test_login_returns_a_bearer_token_for_correct_credentials(
    api_client: AsyncClient,
) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    response = await api_client.post(
        LOGIN_URL, data={"username": "trung", "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_rejects_the_wrong_password(api_client: AsyncClient) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    response = await api_client.post(LOGIN_URL, data={"username": "trung", "password": "wrong"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["type"].endswith("unauthorized")
    assert response.headers["www-authenticate"] == "Bearer"


async def _register_and_log_in(api_client: AsyncClient, username: str = "trung") -> str:
    await api_client.post(
        REGISTER_URL,
        json={"username": username, "password": "correct-horse-battery", "full_name": "Trung"},
    )
    login_response = await api_client.post(
        LOGIN_URL, data={"username": username, "password": "correct-horse-battery"}
    )
    token: str = login_response.json()["access_token"]
    return token


async def test_get_me_returns_the_authenticated_user(api_client: AsyncClient) -> None:
    token = await _register_and_log_in(api_client)

    response = await api_client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["username"] == "trung"


async def test_get_me_without_a_token_is_unauthorized(api_client: AsyncClient) -> None:
    response = await api_client.get(ME_URL)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_put_me_updates_full_name_and_survives_a_reload(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_log_in(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await api_client.put(ME_URL, json={"full_name": "New Name"}, headers=headers)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["full_name"] == "New Name"

    stored = await db_session.scalar(select(User).where(User.username == "trung"))
    assert stored is not None
    assert stored.full_name == "New Name"
