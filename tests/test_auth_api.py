"""Register, log in, and act as the current user — the full matrix.

Every branch decisions.md created for `POST /users/register`,
`POST /users/login`, `GET /users/me` and `PUT /users/me` lives here: the
validation ceilings, the credential failures, every way a bearer token can be
refused, and the two public endpoints that must stay reachable without one.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import JWT_ALGORITHM, create_access_token, decode_access_token
from app.models import User
from tests.factories import TEST_PASSWORD, make_user

REGISTER_URL = "/api/v1/users/register"
LOGIN_URL = "/api/v1/users/login"
ME_URL = "/api/v1/users/me"
PROJECTS_URL = "/api/v1/projects"


def profile_url(username: str) -> str:
    return f"/api/v1/users/{username}/profile"


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


async def test_register_without_a_full_name_stores_null(api_client: AsyncClient) -> None:
    response = await api_client.post(
        REGISTER_URL, json={"username": "noname", "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["full_name"] is None


async def test_register_rejects_a_username_already_taken(api_client: AsyncClient) -> None:
    payload = {"username": "trung", "password": "correct-horse-battery"}
    await api_client.post(REGISTER_URL, json=payload)

    response = await api_client.post(REGISTER_URL, json=payload)

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("username-taken")


async def test_register_rejects_a_duplicate_regardless_of_case(api_client: AsyncClient) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    response = await api_client.post(
        REGISTER_URL, json={"username": "TRUNG", "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("username-taken")


@pytest.mark.parametrize(
    ("username", "reason"),
    [
        ("ab", "shorter than the 3-character floor"),
        ("a b", "a space is outside the allowed charset"),
        ("a/b", "a slash is outside the allowed charset"),
        ("a" * 51, "longer than the 50-character ceiling"),
    ],
)
async def test_register_rejects_an_invalid_username(
    api_client: AsyncClient, username: str, reason: str
) -> None:
    response = await api_client.post(
        REGISTER_URL, json={"username": username, "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, reason


async def test_register_rejects_a_password_below_the_minimum_length(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "1234567"}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_register_rejects_a_password_over_the_byte_ceiling(api_client: AsyncClient) -> None:
    """25 characters of `"ễ"` is 75 bytes — under the character count a naive
    check would allow, over the 72-byte ceiling bcrypt actually enforces."""
    password = "ễ" * 25
    assert len(password) < 72
    assert len(password.encode("utf-8")) > 72

    response = await api_client.post(REGISTER_URL, json={"username": "trung", "password": password})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_login_returns_a_bearer_token_for_correct_credentials(
    api_client: AsyncClient,
) -> None:
    register_response = await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )
    user_id = register_response.json()["id"]

    response = await api_client.post(
        LOGIN_URL, data={"username": "trung", "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == user_id


async def test_login_rejects_the_wrong_password(api_client: AsyncClient) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    response = await api_client.post(LOGIN_URL, data={"username": "trung", "password": "wrong"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["type"].endswith("unauthorized")
    assert response.headers["www-authenticate"] == "Bearer"


async def test_login_rejects_an_unknown_user_with_the_same_detail_as_a_wrong_password(
    api_client: AsyncClient,
) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    unknown = await api_client.post(LOGIN_URL, data={"username": "nobody", "password": "whatever1"})
    wrong_password = await api_client.post(
        LOGIN_URL, data={"username": "trung", "password": "wrong-password"}
    )

    assert unknown.status_code == HTTPStatus.UNAUTHORIZED
    assert wrong_password.status_code == HTTPStatus.UNAUTHORIZED
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


async def test_login_accepts_an_uppercase_username(api_client: AsyncClient) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    response = await api_client.post(
        LOGIN_URL, data={"username": "TRUNG", "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.OK


async def test_login_rejects_a_json_body_instead_of_form(api_client: AsyncClient) -> None:
    await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    response = await api_client.post(
        LOGIN_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


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
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"].endswith("unauthorized")


async def test_get_me_rejects_a_garbage_bearer_token(api_client: AsyncClient) -> None:
    response = await api_client.get(ME_URL, headers={"Authorization": "Bearer garbage"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_get_me_rejects_an_expired_token(api_client: AsyncClient) -> None:
    register_response = await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )
    user_id = register_response.json()["id"]
    expired_issue_time = datetime.now(UTC) - timedelta(
        minutes=settings.access_token_expire_minutes + 1
    )
    token = create_access_token(user_id, now=expired_issue_time)

    response = await api_client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_get_me_rejects_a_token_for_a_deleted_user(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_log_in(api_client)

    deleted = await db_session.scalar(select(User).where(User.username == "trung"))
    assert deleted is not None
    await db_session.delete(deleted)
    await db_session.flush()

    response = await api_client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_get_me_rejects_a_token_signed_with_the_wrong_key(api_client: AsyncClient) -> None:
    register_response = await api_client.post(
        REGISTER_URL, json={"username": "trung", "password": "correct-horse-battery"}
    )
    user_id = register_response.json()["id"]
    now = datetime.now(UTC)
    forged = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=30)},
        "a-different-signing-key-that-is-long-enough",
        algorithm=JWT_ALGORITHM,
    )

    response = await api_client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})

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


async def test_put_me_with_null_clears_the_full_name(api_client: AsyncClient) -> None:
    token = await _register_and_log_in(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await api_client.put(ME_URL, json={"full_name": None}, headers=headers)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["full_name"] is None


async def test_put_me_requires_the_full_name_key(api_client: AsyncClient) -> None:
    token = await _register_and_log_in(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await api_client.put(ME_URL, json={}, headers=headers)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_put_me_ignores_a_username_in_the_body(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_log_in(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await api_client.put(
        ME_URL, json={"full_name": "Still Trung", "username": "somebody-else"}, headers=headers
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["username"] == "trung"

    stored = await db_session.scalar(select(User).where(User.username == "trung"))
    assert stored is not None, "the username in the body must not have been applied"


async def test_put_me_without_a_token_is_unauthorized(api_client: AsyncClient) -> None:
    response = await api_client.put(ME_URL, json={"full_name": "Nobody"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_listing_projects_needs_no_token(api_client: AsyncClient) -> None:
    response = await api_client.get(PROJECTS_URL)

    assert response.status_code == HTTPStatus.OK


async def test_reading_a_profile_needs_no_token(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(make_user("trung"))
    await db_session.flush()

    response = await api_client.get(profile_url("trung"))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["user"]["username"] == "trung"


def test_test_password_matches_the_factory_default() -> None:
    """Guard rail: `_register_and_log_in` and `make_user` must agree on the
    password, or a rewrite of one silently stops testing the other."""
    assert TEST_PASSWORD == "correct-horse-battery"
