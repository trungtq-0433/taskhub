"""The foreign-key behavior of `comment` and `task_assignment`, at the database.

Everything here goes through Core statements, so what is exercised is the
`ON DELETE` clause on each foreign key and not an ORM cascade that might mask
a missing one. No endpoint deletes a task or a user today; these tests are the
only thing that holds the FK choices in place.
"""

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Project, Task, User, task_assignment
from tests.factories import make_user


async def _seed(session: AsyncSession) -> tuple[Task, User, User]:
    """A task plus two users: `x` (author, assignee) and `y` (assigner)."""
    project = Project(name="Tables")
    x = make_user("table-x")
    y = make_user("table-y")
    session.add_all([project, x, y])
    await session.flush()

    task = Task(title="Tabled", project_id=project.id)
    session.add(task)
    await session.flush()
    session.add(Comment(task_id=task.id, author_id=x.id, content="hello"))
    await session.execute(
        insert(task_assignment).values(
            task_id=task.id,
            assignee_id=x.id,
            assigned_by_id=y.id,
        )
    )
    await session.flush()
    return task, x, y


async def test_deleting_a_task_takes_its_comments_and_assignment_history_with_it(
    db_session: AsyncSession,
) -> None:
    task, _, _ = await _seed(db_session)

    await db_session.execute(delete(Task).where(Task.id == task.id))

    comments = await db_session.scalar(
        select(func.count()).select_from(Comment).where(Comment.task_id == task.id)
    )
    history = await db_session.scalar(
        select(func.count())
        .select_from(task_assignment)
        .where(task_assignment.c.task_id == task.id)
    )
    assert (comments, history) == (0, 0)


async def test_deleting_a_mere_assignee_or_author_nulls_the_reference_and_keeps_the_row(
    db_session: AsyncSession,
) -> None:
    task, x, y = await _seed(db_session)

    await db_session.execute(delete(User).where(User.id == x.id))

    author_id = await db_session.scalar(select(Comment.author_id).where(Comment.task_id == task.id))
    row = (
        await db_session.execute(
            select(
                task_assignment.c.assignee_id,
                task_assignment.c.assigned_by_id,
            ).where(task_assignment.c.task_id == task.id)
        )
    ).one()
    assert author_id is None
    assert (row.assignee_id, row.assigned_by_id) == (None, y.id)


async def test_a_user_who_assigned_a_task_cannot_be_deleted_while_that_history_exists(
    db_session: AsyncSession,
) -> None:
    _, _, y = await _seed(db_session)

    with pytest.raises(IntegrityError):
        # The savepoint keeps the test's transaction usable after the refusal.
        async with db_session.begin_nested():
            await db_session.execute(delete(User).where(User.id == y.id))
