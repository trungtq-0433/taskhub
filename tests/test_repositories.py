"""Repository behaviour, against real SQL."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Tag
from app.repositories.project import ProjectRepository
from app.repositories.tag import TagRepository


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
