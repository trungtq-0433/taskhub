"""`BookmarkRepository` behaviour, against real SQL."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Task
from app.repositories.bookmark import BookmarkRepository
from tests.factories import make_user


async def test_exists_is_false_before_any_bookmark(db_session: AsyncSession) -> None:
    project = Project(name="Holder")
    user = make_user("checker")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="Unbookmarked", project_id=project.id)
    db_session.add(task)
    await db_session.flush()

    assert await BookmarkRepository(db_session).exists(user_id=user.id, task_id=task.id) is False


async def test_add_then_exists_is_true(db_session: AsyncSession) -> None:
    project = Project(name="Holder")
    user = make_user("bookmarker")
    db_session.add_all([project, user])
    await db_session.flush()
    task = Task(title="To bookmark", project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    repo = BookmarkRepository(db_session)

    row = await repo.add(user_id=user.id, task_id=task.id)

    assert row.task_id == task.id
    assert row.created_at is not None
    assert await repo.exists(user_id=user.id, task_id=task.id) is True


async def test_exists_is_scoped_to_the_specific_user_and_task(db_session: AsyncSession) -> None:
    project = Project(name="Holder")
    first_user = make_user("first")
    second_user = make_user("second")
    db_session.add_all([project, first_user, second_user])
    await db_session.flush()
    tasks = [Task(title=f"T{i}", project_id=project.id) for i in range(2)]
    db_session.add_all(tasks)
    await db_session.flush()
    repo = BookmarkRepository(db_session)

    await repo.add(user_id=first_user.id, task_id=tasks[0].id)

    assert await repo.exists(user_id=first_user.id, task_id=tasks[0].id) is True
    assert await repo.exists(user_id=second_user.id, task_id=tasks[0].id) is False
    assert await repo.exists(user_id=first_user.id, task_id=tasks[1].id) is False
