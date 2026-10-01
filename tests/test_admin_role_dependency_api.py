"""`verify_admin_role` through the real dependency chain, with real tokens,
against the throwaway app `permission_client` (see `conftest.py`) builds —
never the shared `app`, never the dev database.
"""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole
from tests.factories import auth_headers, make_user


async def test_admin_reaches_the_admin_only_route(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    admin = make_user("admin-caller", role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()

    response = await permission_client.get("/admin-only", headers=auth_headers(admin))

    assert response.status_code == HTTPStatus.OK


async def test_plain_user_is_refused_with_403_admin_required(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    user = make_user("plain-caller")
    db_session.add(user)
    await db_session.flush()

    response = await permission_client.get("/admin-only", headers=auth_headers(user))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("admin-required")


async def test_inactive_admin_is_refused_with_403_inactive_user(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    """`get_current_active_user` runs before `verify_admin_role` (the active
    check is the outer layer), so a disabled admin sees `inactive-user`, not
    `admin-required`."""
    admin = make_user("disabled-admin", role=UserRole.ADMIN, is_active=False)
    db_session.add(admin)
    await db_session.flush()

    response = await permission_client.get("/admin-only", headers=auth_headers(admin))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("inactive-user")


async def test_admin_only_route_requires_a_token(permission_client: AsyncClient) -> None:
    response = await permission_client.get("/admin-only")

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_demoting_an_admin_bites_on_the_same_token(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    """The role is read from the row on every request, never from the
    token, so a demotion between the token's issue and its use bites on the
    very next request."""
    admin = make_user("soon-demoted", role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()
    headers = auth_headers(admin)

    admin.role = UserRole.USER
    await db_session.flush()

    response = await permission_client.get("/admin-only", headers=headers)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("admin-required")
