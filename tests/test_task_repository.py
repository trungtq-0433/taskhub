"""`TaskRepository` behaviour, against real SQL.

Split out of `test_repositories.py`: the paginate/filter surface here is
sizeable enough on its own that folding it back in would push that file past
this codebase's file-size ceiling.
"""

from fastapi_pagination import Params
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskPriority, TaskStatus
from app.models import Project, Tag, Task, User
from app.repositories.task import TaskRepository
from app.schemas.task import TaskFilter
from tests.factories import make_user


async def _seed_task_graph(session: AsyncSession) -> tuple[Project, User, list[Tag]]:
    """One project, one user, two tags, and a task wearing all of them."""
    project = Project(name="Graph")
    user = make_user("assignee", full_name="The Assignee")
    tags = [Tag(name="alpha"), Tag(name="beta")]
    session.add_all([project, user, *tags])
    await session.flush()

    task = Task(title="Wired", project_id=project.id, assignee_id=user.id)
    task.tags = tags
    session.add(task)
    await session.flush()
    return project, user, tags


async def test_paginate_loads_tags_and_assignee_eagerly(db_session: AsyncSession) -> None:
    """Read the relationships with the identity map cleared.

    Without `expunge_all()` the objects are still in the session, so the
    attributes read straight out of memory and the assertion passes whether or
    not the eager options ran. Cleared, an unloaded attribute has to go back to
    the database — which under AsyncSession raises MissingGreenlet rather than
    quietly issuing a query.
    """
    project, user, tags = await _seed_task_graph(db_session)
    repo = TaskRepository(db_session)

    page = await repo.paginate(None, project_id=project.id, params=Params(size=10))
    [task] = page.items
    db_session.expunge_all()

    assert {tag.name for tag in task.tags} == {tag.name for tag in tags}
    assert task.assignee is not None
    assert task.assignee.username == user.username


async def test_paginate_excludes_other_projects(db_session: AsyncSession) -> None:
    project, _, _ = await _seed_task_graph(db_session)
    other = Project(name="Elsewhere")
    db_session.add(other)
    await db_session.flush()
    db_session.add(Task(title="Not mine", project_id=other.id))
    await db_session.flush()

    page = await TaskRepository(db_session).paginate(
        None, project_id=project.id, params=Params(size=10)
    )

    assert [task.title for task in page.items] == ["Wired"]


async def test_paginate_with_no_project_id_spans_every_project(db_session: AsyncSession) -> None:
    project, _, _ = await _seed_task_graph(db_session)
    other = Project(name="Elsewhere too")
    db_session.add(other)
    await db_session.flush()
    db_session.add(Task(title="Also mine", project_id=other.id))
    await db_session.flush()

    page = await TaskRepository(db_session).paginate(
        TaskFilter(), project_id=None, params=Params(size=10)
    )

    assert {task.project_id for task in page.items} == {project.id, other.id}


async def test_paginate_with_no_task_filter_applies_no_status_or_priority_condition(
    db_session: AsyncSession,
) -> None:
    """The nested route's own contract: `task_filter=None` means no `WHERE`
    beyond `project_id`, whatever the task's status or priority."""
    project, _, _ = await _seed_task_graph(db_session)
    db_session.add(Task(title="Done one", project_id=project.id, status=TaskStatus.DONE))
    await db_session.flush()

    page = await TaskRepository(db_session).paginate(
        None, project_id=project.id, params=Params(size=10)
    )

    assert {task.title for task in page.items} == {"Wired", "Done one"}


async def test_paginate_filters_status_and_priority_together(db_session: AsyncSession) -> None:
    """One AND case: both filters present narrows to their intersection."""
    project, _, _ = await _seed_task_graph(db_session)
    db_session.add_all(
        [
            Task(
                title="todo-high",
                project_id=project.id,
                status=TaskStatus.TODO,
                priority=TaskPriority.HIGH,
            ),
            Task(
                title="todo-low",
                project_id=project.id,
                status=TaskStatus.TODO,
                priority=TaskPriority.LOW,
            ),
            Task(
                title="done-high",
                project_id=project.id,
                status=TaskStatus.DONE,
                priority=TaskPriority.HIGH,
            ),
        ]
    )
    await db_session.flush()

    page = await TaskRepository(db_session).paginate(
        TaskFilter(status=TaskStatus.TODO, priority=TaskPriority.HIGH),
        project_id=None,
        params=Params(size=10),
    )

    assert [task.title for task in page.items] == ["todo-high"]


async def test_paginate_total_matches_the_same_filters_as_items(db_session: AsyncSession) -> None:
    """`total` and `items` come off the same statement (`apaginate` builds its
    count query from it), so they can never disagree about which rows match."""
    project, _, _ = await _seed_task_graph(db_session)
    db_session.add(Task(title="Second", project_id=project.id))
    await db_session.flush()

    page = await TaskRepository(db_session).paginate(
        None, project_id=project.id, params=Params(size=10)
    )

    assert page.total == len(page.items)


async def test_get_returns_none_for_a_missing_task(db_session: AsyncSession) -> None:
    assert await TaskRepository(db_session).get(999_999) is None


async def test_get_returns_the_task(db_session: AsyncSession) -> None:
    project, _, _ = await _seed_task_graph(db_session)
    [task] = (
        await TaskRepository(db_session).paginate(
            None, project_id=project.id, params=Params(size=10)
        )
    ).items

    found = await TaskRepository(db_session).get(task.id)

    assert found is not None
    assert found.title == "Wired"
