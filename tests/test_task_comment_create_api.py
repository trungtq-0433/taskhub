"""`POST /tasks/{task_id}/comments`: any active user, content stripped and capped."""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import COMMENT_CONTENT_MAX_LENGTH, MAX_ID
from app.models import Project, Task, User
from tests.factories import auth_headers, make_user


def comments_url(task_id: int) -> str:
    return f"/api/v1/tasks/{task_id}/comments"


async def _seed(db_session: AsyncSession) -> tuple[User, Task]:
    project = Project(name="Holder")
    user = make_user("commenter")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Discuss me", project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    return user, task


async def test_commenting_returns_201_with_the_author_and_the_stripped_content(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    user, task = await _seed(db_session)

    response = await api_client.post(
        comments_url(task.id), json={"content": "  hi  "}, headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["content"] == "hi"
    assert body["author"]["id"] == user.id
    assert body["task_id"] == task.id
    assert body["created_at"]
    assert body["updated_at"]
    assert "location" not in response.headers


async def test_the_author_and_task_come_from_the_token_and_path_not_the_body(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    user, task = await _seed(db_session)
    other = make_user("someone-else")
    db_session.add(other)
    await db_session.flush()

    response = await api_client.post(
        comments_url(task.id),
        json={"content": "hello", "author_id": other.id, "task_id": task.id + 1000},
        headers=auth_headers(user),
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["author"]["id"] == user.id
    assert body["task_id"] == task.id


async def test_commenting_on_a_missing_task_is_404_task_not_found(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    user, _ = await _seed(db_session)

    response = await api_client.post(
        comments_url(999_999), json={"content": "hi"}, headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("task-not-found")


@pytest.mark.parametrize("content", ["", "   "])
async def test_empty_or_whitespace_only_content_is_422_validation(
    db_session: AsyncSession, api_client: AsyncClient, content: str
) -> None:
    user, task = await _seed(db_session)

    response = await api_client.post(
        comments_url(task.id), json={"content": content}, headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (COMMENT_CONTENT_MAX_LENGTH, HTTPStatus.CREATED),
        (COMMENT_CONTENT_MAX_LENGTH + 1, HTTPStatus.UNPROCESSABLE_ENTITY),
    ],
)
async def test_content_length_is_capped_at_the_constant(
    db_session: AsyncSession, api_client: AsyncClient, length: int, expected: HTTPStatus
) -> None:
    user, task = await _seed(db_session)

    response = await api_client.post(
        comments_url(task.id), json={"content": "x" * length}, headers=auth_headers(user)
    )

    assert response.status_code == expected


@pytest.mark.parametrize("task_id", [0, MAX_ID + 1])
async def test_an_out_of_range_task_id_is_422_validation(
    db_session: AsyncSession, api_client: AsyncClient, task_id: int
) -> None:
    user, _ = await _seed(db_session)

    response = await api_client.post(
        comments_url(task_id), json={"content": "hi"}, headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("validation")


async def test_commenting_without_a_token_is_401(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, task = await _seed(db_session)

    response = await api_client.post(comments_url(task.id), json={"content": "hi"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_a_disabled_user_cannot_comment_403_inactive_user(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    user, task = await _seed(db_session)
    user.is_active = False
    await db_session.flush()

    response = await api_client.post(
        comments_url(task.id), json={"content": "hi"}, headers=auth_headers(user)
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("inactive-user")
