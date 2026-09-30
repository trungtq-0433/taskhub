"""`POST /tasks/{task_id}/bookmark`: login required, POST only, not idempotent.

Split out of `test_tasks_api.py`, which already covers the nested
list/create route and would grow past this codebase's file-size ceiling if
this surface stayed folded in.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Task
from app.repositories.bookmark import BookmarkRepository
from tests.factories import auth_headers, make_user


def bookmark_url(task_id: int) -> str:
    return f"/api/v1/tasks/{task_id}/bookmark"


async def test_bookmarking_a_task_returns_201_with_the_task_id_and_created_at(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project = Project(name="Holder")
    user = make_user("worker")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Bookmark me", project_id=project.id)
    db_session.add(task)
    await db_session.flush()

    response = await api_client.post(bookmark_url(task.id), headers=auth_headers(user))

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["task_id"] == task.id
    assert "created_at" in body


async def test_bookmarking_the_same_task_twice_is_a_409(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project = Project(name="Holder")
    user = make_user("worker")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Bookmark me twice", project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    headers = auth_headers(user)

    first = await api_client.post(bookmark_url(task.id), headers=headers)
    second = await api_client.post(bookmark_url(task.id), headers=headers)

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT
    assert second.json()["type"].endswith("already-bookmarked")


async def test_two_different_users_can_each_bookmark_the_same_task(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project = Project(name="Holder")
    first_user = make_user("first-worker")
    second_user = make_user("second-worker")
    db_session.add_all([project, first_user, second_user])
    await db_session.flush()
    task = Task(title="Shared favourite", project_id=project.id)
    db_session.add(task)
    await db_session.flush()

    first = await api_client.post(bookmark_url(task.id), headers=auth_headers(first_user))
    second = await api_client.post(bookmark_url(task.id), headers=auth_headers(second_user))

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED


async def test_one_user_can_bookmark_two_different_tasks(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project = Project(name="Holder")
    user = make_user("worker")
    db_session.add_all([project, user])
    await db_session.flush()
    tasks = [Task(title=f"T{i}", project_id=project.id) for i in range(2)]
    db_session.add_all(tasks)
    await db_session.flush()
    headers = auth_headers(user)

    first = await api_client.post(bookmark_url(tasks[0].id), headers=headers)
    second = await api_client.post(bookmark_url(tasks[1].id), headers=headers)

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED


async def test_bookmarking_an_unknown_task_is_a_404(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    user = make_user("lonely")
    db_session.add(user)
    await db_session.flush()

    response = await api_client.post(bookmark_url(999_999), headers=auth_headers(user))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("task-not-found")


async def test_bookmarking_requires_a_logged_in_user(api_client: AsyncClient) -> None:
    response = await api_client.post(bookmark_url(999_999))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_an_inactive_users_token_is_refused_with_403(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project = Project(name="Holder")
    user = make_user("disabled-worker", is_active=False)
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Bookmark me", project_id=project.id)
    db_session.add(task)
    await db_session.flush()

    response = await api_client.post(bookmark_url(task.id), headers=auth_headers(user))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("inactive-user")


async def test_a_token_minted_while_active_is_refused_after_deactivation(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """`is_active` is read from the row on every request, not from the
    token, so a deactivation between the token's issue and its use bites on
    the very next request."""
    project = Project(name="Holder")
    user = make_user("soon-disabled")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Bookmark me", project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    headers = auth_headers(user)

    user.is_active = False
    await db_session.flush()

    response = await api_client.post(bookmark_url(task.id), headers=headers)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("inactive-user")


async def test_a_lost_race_against_the_pre_check_still_answers_409(
    db_session: AsyncSession, api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two interleaved requests can both pass `BookmarkRepository.exists`
    before either commits — only one insert wins the composite primary key,
    and the loser must see the same 409 as the ordinary duplicate case, not
    a raw `IntegrityError` surfacing as a generic conflict.

    Monkeypatching `exists` to always answer `False` simulates the race
    without actually running two requests concurrently: the pre-check is
    fooled into thinking no bookmark exists, so the code path that follows
    is exactly the one a real interleaving would take.
    """
    project = Project(name="Holder")
    user = make_user("worker")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Raced", project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    headers = auth_headers(user)

    await api_client.post(bookmark_url(task.id), headers=headers)

    async def fake_exists(self: BookmarkRepository, *, user_id: int, task_id: int) -> bool:
        return False

    monkeypatch.setattr(BookmarkRepository, "exists", fake_exists)

    response = await api_client.post(bookmark_url(task.id), headers=headers)

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["type"].endswith("already-bookmarked")


async def test_delete_bookmark_is_not_a_route(api_client: AsyncClient) -> None:
    """Not idempotent by design: no `DELETE` exists to undo a bookmark."""
    response = await api_client.delete(bookmark_url(999_999))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
