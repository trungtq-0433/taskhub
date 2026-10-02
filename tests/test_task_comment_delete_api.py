"""`DELETE /tasks/{task_id}/comments/{comment_id}`: author, admin or project owner.

Every 404 is answered before the 403, so a caller who may not delete learns
nothing about comments that exist elsewhere.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole
from app.core.exceptions import NotFoundError
from app.models import Comment, Project, Task, User
from app.services.comment import CommentService
from app.services.project import ProjectService
from app.services.task import TaskService
from tests.factories import auth_headers, make_user


def comment_url(task_id: int, comment_id: int) -> str:
    return f"/api/v1/tasks/{task_id}/comments/{comment_id}"


async def seed_comment(
    db_session: AsyncSession, *, owner: User | None = None
) -> tuple[User, User, Task, Comment]:
    """An author, a bystander, a task (optionally in a project owned by `owner`) and a comment."""
    author = make_user("the-author")
    bystander = make_user("the-bystander")
    db_session.add_all([author, bystander])
    await db_session.flush()
    project = Project(name="Holder", owner_id=owner.id if owner else None)
    db_session.add(project)
    await db_session.flush()
    task = Task(title="Discussed", project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    comment = Comment(task_id=task.id, author_id=author.id, content="note")
    db_session.add(comment)
    await db_session.flush()
    return author, bystander, task, comment


async def comment_exists(db_session: AsyncSession, comment_id: int) -> bool:
    found = await db_session.scalar(select(Comment.id).where(Comment.id == comment_id))
    return found is not None


async def test_the_author_can_delete_their_comment_and_it_is_gone(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    author, _, task, comment = await seed_comment(db_session)

    response = await api_client.delete(
        comment_url(task.id, comment.id), headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    assert not await comment_exists(db_session, comment.id)


async def test_an_admin_can_delete_someone_elses_comment(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, _, task, comment = await seed_comment(db_session)
    admin = make_user("an-admin", role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()

    response = await api_client.delete(
        comment_url(task.id, comment.id), headers=auth_headers(admin)
    )

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert not await comment_exists(db_session, comment.id)


async def test_the_projects_owner_can_delete_a_comment_on_its_task(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    owner = make_user("project-owner")
    db_session.add(owner)
    await db_session.flush()
    _, _, task, comment = await seed_comment(db_session, owner=owner)

    response = await api_client.delete(
        comment_url(task.id, comment.id), headers=auth_headers(owner)
    )

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert not await comment_exists(db_session, comment.id)


async def test_another_user_is_403_comment_forbidden_and_the_comment_survives(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, bystander, task, comment = await seed_comment(db_session)

    response = await api_client.delete(
        comment_url(task.id, comment.id), headers=auth_headers(bystander)
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"].endswith("comment-forbidden")
    assert await comment_exists(db_session, comment.id)


async def test_a_missing_task_is_404_task_not_found_even_for_a_caller_who_would_be_forbidden(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, bystander, _, comment = await seed_comment(db_session)

    response = await api_client.delete(
        comment_url(999_999, comment.id), headers=auth_headers(bystander)
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("task-not-found")


async def test_a_missing_comment_is_404_comment_not_found(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    author, _, task, _ = await seed_comment(db_session)

    response = await api_client.delete(comment_url(task.id, 999_999), headers=auth_headers(author))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("comment-not-found")


async def test_a_comment_under_another_task_is_404_comment_not_found_not_403(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    _, bystander, task, _ = await seed_comment(db_session)
    other_task = Task(title="Elsewhere", project_id=task.project_id)
    db_session.add(other_task)
    await db_session.flush()
    elsewhere = Comment(task_id=other_task.id, author_id=None, content="not here")
    db_session.add(elsewhere)
    await db_session.flush()

    response = await api_client.delete(
        comment_url(task.id, elsewhere.id), headers=auth_headers(bystander)
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("comment-not-found")
    assert await comment_exists(db_session, elsewhere.id)


async def test_deleting_the_same_comment_twice_is_404_the_second_time(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    author, _, task, comment = await seed_comment(db_session)
    headers = auth_headers(author)

    first = await api_client.delete(comment_url(task.id, comment.id), headers=headers)
    second = await api_client.delete(comment_url(task.id, comment.id), headers=headers)

    assert first.status_code == HTTPStatus.NO_CONTENT
    assert second.status_code == HTTPStatus.NOT_FOUND
    assert second.json()["type"].endswith("comment-not-found")


async def test_a_delete_that_finds_the_row_already_gone_is_comment_not_found(
    db_session: AsyncSession,
) -> None:
    """The race branch: the dependency's read passed, then the row vanished."""
    _, _, task, comment = await seed_comment(db_session)
    service = CommentService(
        db_session, tasks=TaskService(db_session), projects=ProjectService(db_session)
    )

    await service.delete(task_id=task.id, comment_id=comment.id)
    with pytest.raises(NotFoundError) as raised:
        await service.delete(task_id=task.id, comment_id=comment.id)

    assert raised.value.problem_type == "comment-not-found"
