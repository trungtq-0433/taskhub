"""Repository behaviour, against real SQL."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskStatus
from app.models import Project, Tag, Task, User
from app.repositories.project import ProjectRepository
from app.repositories.tag import TagRepository
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from tests.factories import make_user


async def _seed(session: AsyncSession, count: int) -> list[Project]:
    projects = [Project(name=f"Project {i:02d}") for i in range(count)]
    session.add_all(projects)
    await session.flush()
    return projects


async def test_get_returns_none_for_a_missing_row(db_session: AsyncSession) -> None:
    assert await ProjectRepository(db_session).get(999) is None


async def test_get_returns_the_row(db_session: AsyncSession) -> None:
    [project] = await _seed(db_session, 1)

    found = await ProjectRepository(db_session).get(project.id)

    assert found is not None
    assert found.name == project.name


async def test_add_flushes_but_does_not_commit(db_session: AsyncSession) -> None:
    """A repository that commits takes the transaction away from the service."""
    repo = ProjectRepository(db_session)

    project = await repo.add(Project(name="Fresh"))

    assert project.id is not None, "flush must assign the primary key"
    assert db_session.in_transaction(), "the transaction must still be open"


async def test_list_returns_the_requested_slice(db_session: AsyncSession) -> None:
    await _seed(db_session, 7)
    repo = ProjectRepository(db_session)

    page_two = await repo.list(offset=3, limit=3)

    assert [p.name for p in page_two] == ["Project 03", "Project 04", "Project 05"]


async def test_count_is_independent_of_the_slice(db_session: AsyncSession) -> None:
    """`Page` needs the full total, not the length of the page."""
    await _seed(db_session, 7)
    repo = ProjectRepository(db_session)

    assert len(await repo.list(offset=0, limit=3)) == 3
    assert await repo.count() == 7


async def test_delete_removes_the_row(db_session: AsyncSession) -> None:
    [project] = await _seed(db_session, 1)
    repo = ProjectRepository(db_session)

    await repo.delete(project)

    assert await db_session.scalar(select(func.count()).select_from(Project)) == 0


async def test_name_exists_finds_a_clash(db_session: AsyncSession) -> None:
    await _seed(db_session, 1)
    repo = ProjectRepository(db_session)

    assert await repo.name_exists("Project 00") is True
    assert await repo.name_exists("Something else") is False


async def test_name_exists_does_not_report_a_row_against_itself(db_session: AsyncSession) -> None:
    """The PATCH case: renaming a row to the name it already has is not a clash."""
    [project] = await _seed(db_session, 1)
    repo = ProjectRepository(db_session)

    assert await repo.name_exists("Project 00", exclude_id=project.id) is False


async def test_tag_repository_covers_the_same_ground(db_session: AsyncSession) -> None:
    repo = TagRepository(db_session)
    tag = await repo.add(Tag(name="urgent", color="#ff0000"))

    assert await repo.get(tag.id) is not None
    assert await repo.count() == 1
    assert await repo.name_exists("urgent") is True
    assert await repo.name_exists("urgent", exclude_id=tag.id) is False

    await repo.delete(tag)
    assert await repo.count() == 0


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


async def test_list_for_project_loads_tags_and_assignee_eagerly(db_session: AsyncSession) -> None:
    """Read the relationships with the identity map cleared.

    Without `expunge_all()` the objects are still in the session, so the
    attributes read straight out of memory and the assertion passes whether or
    not the eager options ran. Cleared, an unloaded attribute has to go back to
    the database — which under AsyncSession raises MissingGreenlet rather than
    quietly issuing a query.
    """
    project, user, tags = await _seed_task_graph(db_session)
    repo = TaskRepository(db_session)

    [task] = await repo.list_for_project(project.id, offset=0, limit=10)
    db_session.expunge_all()

    assert {tag.name for tag in task.tags} == {tag.name for tag in tags}
    assert task.assignee is not None
    assert task.assignee.username == user.username


async def test_list_for_project_excludes_other_projects(db_session: AsyncSession) -> None:
    project, _, _ = await _seed_task_graph(db_session)
    other = Project(name="Elsewhere")
    db_session.add(other)
    await db_session.flush()
    db_session.add(Task(title="Not mine", project_id=other.id))
    await db_session.flush()

    tasks = await TaskRepository(db_session).list_for_project(project.id, offset=0, limit=10)

    assert [task.title for task in tasks] == ["Wired"]


async def test_count_by_status_returns_every_status_including_the_empty_ones(
    db_session: AsyncSession,
) -> None:
    project, user, _ = await _seed_task_graph(db_session)
    db_session.add(Task(title="Second", project_id=project.id, assignee_id=user.id))
    await db_session.flush()

    counts = await TaskRepository(db_session).count_by_status_for_assignee(user.id)

    assert counts == {TaskStatus.TODO: 2, TaskStatus.DOING: 0, TaskStatus.DONE: 0}


async def test_count_projects_ignores_projects_with_no_owner(db_session: AsyncSession) -> None:
    """An ownerless project counts toward nobody — that is the correct reading."""
    user = make_user("owner")
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([Project(name="Owned", owner_id=user.id), Project(name="Orphan")])
    await db_session.flush()

    assert await UserRepository(db_session).count_projects(user.id) == 1


async def test_get_by_username_finds_the_row(db_session: AsyncSession) -> None:
    db_session.add(make_user("trung"))
    await db_session.flush()
    repo = UserRepository(db_session)

    assert (found := await repo.get_by_username("trung")) is not None
    assert found.username == "trung"
    assert await repo.get_by_username("nobody") is None


async def test_list_by_ids_returns_fewer_rows_than_asked_for(db_session: AsyncSession) -> None:
    """A missing id is not an error here — the service turns the gap into a 422."""
    tags = [Tag(name="one"), Tag(name="two")]
    db_session.add_all(tags)
    await db_session.flush()
    repo = TagRepository(db_session)

    found = await repo.list_by_ids([tags[0].id, 9999])

    assert [tag.name for tag in found] == ["one"]
    assert await repo.list_by_ids([]) == []
