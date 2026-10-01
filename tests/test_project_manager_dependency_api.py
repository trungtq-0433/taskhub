"""`verify_project_manager` through the real dependency chain, with real
tokens, against the throwaway app `permission_client` (see `conftest.py`)
builds — never the shared `app`, never the dev database.
"""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole
from app.models import Project
from tests.factories import auth_headers, make_user


async def test_owner_reaches_the_manager_only_route(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    owner = make_user("owner-caller")
    db_session.add(owner)
    await db_session.flush()
    project = Project(name="Owned", owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()

    response = await permission_client.get(
        f"/projects/{project.id}/manager-only", headers=auth_headers(owner)
    )

    assert response.status_code == HTTPStatus.OK


async def test_another_user_is_refused_with_403_project_manager_required(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    owner = make_user("owner-of-the-project")
    other = make_user("not-the-owner")
    db_session.add_all([owner, other])
    await db_session.flush()
    project = Project(name="Someone else's", owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()

    response = await permission_client.get(
        f"/projects/{project.id}/manager-only", headers=auth_headers(other)
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("project-manager-required")


async def test_admin_reaches_an_ownerless_project(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    admin = make_user("admin-for-ownerless", role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Ownerless")
    db_session.add(project)
    await db_session.flush()

    response = await permission_client.get(
        f"/projects/{project.id}/manager-only", headers=auth_headers(admin)
    )

    assert response.status_code == HTTPStatus.OK


async def test_plain_user_is_refused_on_an_ownerless_project(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    user = make_user("user-for-ownerless")
    db_session.add(user)
    await db_session.flush()
    project = Project(name="Ownerless too")
    db_session.add(project)
    await db_session.flush()

    response = await permission_client.get(
        f"/projects/{project.id}/manager-only", headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("project-manager-required")


async def test_missing_project_is_a_404_project_not_found(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    user = make_user("caller-for-missing-project")
    db_session.add(user)
    await db_session.flush()

    response = await permission_client.get(
        "/projects/999999/manager-only", headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("project-not-found")


async def test_demoting_an_admin_bites_on_the_manager_route_too(
    db_session: AsyncSession, permission_client: AsyncClient
) -> None:
    admin = make_user("soon-demoted-manager", role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Ownerless for demotion")
    db_session.add(project)
    await db_session.flush()
    headers = auth_headers(admin)

    admin.role = UserRole.USER
    await db_session.flush()

    response = await permission_client.get(f"/projects/{project.id}/manager-only", headers=headers)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("project-manager-required")
