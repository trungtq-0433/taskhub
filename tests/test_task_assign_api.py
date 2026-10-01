"""`POST /tasks/{task_id}/assign`: what a successful call does."""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Tag, Task, User, task_assignment
from tests.factories import auth_headers, make_user


async def _seed(
    session: AsyncSession, *, assigned_to: str | None = "alice"
) -> tuple[Task, dict[str, User]]:
    """A task (one tag), its current assignee `alice`, and two other users."""
    users = {name: make_user(name) for name in ("alice", "bob", "carol")}
    project, tag = Project(name="Holder"), Tag(name="urgent")
    session.add_all([project, tag, *users.values()])
    await session.flush()
    task = Task(title="Ship it", project_id=project.id)
    task.assignee = users[assigned_to] if assigned_to else None
    task.tags = [tag]
    session.add(task)
    await session.flush()
    return task, users


def assign_url(task_id: int) -> str:
    return f"/api/v1/tasks/{task_id}/assign"


async def _history(session: AsyncSession, task_id: int) -> list[tuple[int | None, int, int]]:
    rows = await session.execute(
        select(
            task_assignment.c.previous_assignee_id,
            task_assignment.c.assignee_id,
            task_assignment.c.assigned_by_id,
        )
        .where(task_assignment.c.task_id == task_id)
        .order_by(task_assignment.c.id)
    )
    return [tuple(row) for row in rows.all()]


async def test_any_active_user_can_assign_a_task_and_gets_200_with_the_new_assignee(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, users = await _seed(db_session)

    response = await api_client.post(
        assign_url(task.id),
        json={"assignee_id": users["bob"].id},
        headers=auth_headers(users["carol"]),  # neither owner nor admin
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["assignee"]["id"] == users["bob"].id
    assert [tag["name"] for tag in body["tags"]] == ["urgent"]


async def test_assigning_records_one_history_row_with_the_previous_assignee_and_the_caller(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, users = await _seed(db_session)

    await api_client.post(
        assign_url(task.id),
        json={"assignee_id": users["bob"].id},
        headers=auth_headers(users["carol"]),
    )

    assert await _history(db_session, task.id) == [
        (users["alice"].id, users["bob"].id, users["carol"].id)
    ]


async def test_assigning_an_unassigned_task_records_a_null_previous_assignee(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, users = await _seed(db_session, assigned_to=None)

    response = await api_client.post(
        assign_url(task.id),
        json={"assignee_id": users["bob"].id},
        headers=auth_headers(users["carol"]),
    )

    assert response.status_code == HTTPStatus.OK
    assert await _history(db_session, task.id) == [(None, users["bob"].id, users["carol"].id)]


async def test_a_user_can_assign_a_task_to_themselves(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, users = await _seed(db_session)

    response = await api_client.post(
        assign_url(task.id),
        json={"assignee_id": users["bob"].id},
        headers=auth_headers(users["bob"]),
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["assignee"]["id"] == users["bob"].id
    assert await _history(db_session, task.id) == [
        (users["alice"].id, users["bob"].id, users["bob"].id)
    ]


async def test_assigning_the_current_assignee_again_is_200_with_no_new_history_row(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, users = await _seed(db_session)

    response = await api_client.post(
        assign_url(task.id),
        json={"assignee_id": users["alice"].id},
        headers=auth_headers(users["carol"]),
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["assignee"]["id"] == users["alice"].id
    assert [tag["name"] for tag in body["tags"]] == ["urgent"]
    assert await _history(db_session, task.id) == []


async def test_reassigning_a_current_assignee_who_was_since_disabled_is_200_with_no_history_row(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, users = await _seed(db_session)
    users["alice"].is_active = False
    await db_session.flush()

    response = await api_client.post(
        assign_url(task.id),
        json={"assignee_id": users["alice"].id},
        headers=auth_headers(users["carol"]),
    )

    assert response.status_code == HTTPStatus.OK
    assert await _history(db_session, task.id) == []
