"""`POST /tasks/{task_id}/assign`: every way it says no."""

from http import HTTPStatus
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MAX_ID
from app.models import Project, Task, User, task_assignment
from tests.factories import auth_headers, make_user


async def _seed(session: AsyncSession) -> tuple[Task, User, User, User]:
    """A task assigned to `alice`; returns (task, alice, bob, caller)."""
    alice, bob, caller = make_user("alice"), make_user("bob"), make_user("caller")
    project = Project(name="Holder")
    session.add_all([project, alice, bob, caller])
    await session.flush()
    task = Task(title="Ship it", project_id=project.id)
    task.assignee = alice
    session.add(task)
    await session.flush()
    return task, alice, bob, caller


def assign_url(task_id: int) -> str:
    return f"/api/v1/tasks/{task_id}/assign"


async def _history_count(session: AsyncSession, task_id: int) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(task_assignment)
            .where(task_assignment.c.task_id == task_id)
        )
    ) or 0


async def test_assigning_an_unknown_user_is_422_assignee_not_found(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, _, _, caller = await _seed(db_session)

    response = await api_client.post(
        assign_url(task.id), json={"assignee_id": MAX_ID}, headers=auth_headers(caller)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("assignee-not-found")


async def test_assigning_a_disabled_user_is_422_assignee_inactive_and_changes_nothing(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, alice, bob, caller = await _seed(db_session)
    bob.is_active = False
    await db_session.flush()

    response = await api_client.post(
        assign_url(task.id), json={"assignee_id": bob.id}, headers=auth_headers(caller)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("assignee-inactive")
    await db_session.refresh(task)
    assert task.assignee_id == alice.id
    assert await _history_count(db_session, task.id) == 0


async def test_assigning_a_missing_task_is_404_task_not_found_even_with_a_disabled_assignee(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, _, bob, caller = await _seed(db_session)
    bob.is_active = False
    await db_session.flush()

    response = await api_client.post(
        assign_url(MAX_ID), json={"assignee_id": bob.id}, headers=auth_headers(caller)
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("task-not-found")


@pytest.mark.parametrize(
    "body", [{}, {"assignee_id": None}, {"assignee_id": 0}, {"assignee_id": 2**31}]
)
async def test_a_missing_null_or_out_of_range_assignee_id_is_422_validation(
    db_session: AsyncSession, api_client: AsyncClient, body: dict[str, Any]
) -> None:
    task, _, _, caller = await _seed(db_session)

    response = await api_client.post(assign_url(task.id), json=body, headers=auth_headers(caller))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


@pytest.mark.parametrize("task_id", [0, 2**31])
async def test_an_out_of_range_task_id_is_422_validation(
    db_session: AsyncSession, api_client: AsyncClient, task_id: int
) -> None:
    _, _, bob, caller = await _seed(db_session)

    response = await api_client.post(
        assign_url(task_id), json={"assignee_id": bob.id}, headers=auth_headers(caller)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


async def test_assigning_without_a_token_is_401(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, _, bob, _ = await _seed(db_session)

    response = await api_client.post(assign_url(task.id), json={"assignee_id": bob.id})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_a_disabled_caller_is_403_inactive_user(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    task, _, bob, caller = await _seed(db_session)
    caller.is_active = False
    await db_session.flush()

    response = await api_client.post(
        assign_url(task.id), json={"assignee_id": bob.id}, headers=auth_headers(caller)
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("inactive-user")
