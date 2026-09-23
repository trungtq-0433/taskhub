"""Proof that services actually commit.

Every other database test runs inside a transaction that is rolled back, and
`api_client` hands the same session to every request in a test. That is what
makes the suite fast and isolated — and it is also blind to a missing
`commit()`, because a flushed-but-uncommitted row is visible to the session
that wrote it.

So these tests deliberately do not use that harness. They commit for real
against the test database, verify through a genuinely separate session, and
clean up after themselves. Slower, and the only place the durability of a
write is actually established.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Project, Tag, Task, User
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.tag import TagCreate
from app.schemas.task import TaskCreate
from app.services.project import ProjectService
from app.services.tag import TagService
from app.services.task import TaskService


@pytest.fixture
async def committing_sessions(
    _engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Real sessions that really commit, with the tables emptied afterwards."""
    factory = async_sessionmaker(bind=_engine, expire_on_commit=False)
    yield factory

    async with factory() as cleanup:
        # Task first: its FK to project is ON DELETE RESTRICT, so emptying
        # `project` while a task still points at one is refused outright.
        # Association rows go with the task through the database's cascade.
        await cleanup.execute(delete(Task))
        await cleanup.execute(delete(Project))
        await cleanup.execute(delete(Tag))
        await cleanup.execute(delete(User))
        await cleanup.commit()


async def test_create_survives_into_a_separate_session(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Without `commit()` in the service, the second session sees nothing."""
    async with committing_sessions() as writing:
        created = await ProjectService(writing).create(ProjectCreate(name="Durable"))

    async with committing_sessions() as reading:
        found = await reading.get(Project, created.id)

    assert found is not None, "the row did not outlive the session that wrote it"
    assert found.name == "Durable"


async def test_update_survives_into_a_separate_session(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with committing_sessions() as writing:
        service = ProjectService(writing)
        created = await service.create(ProjectCreate(name="Before"))
        await service.update(created.id, ProjectUpdate(name="After"))

    async with committing_sessions() as reading:
        found = await reading.get(Project, created.id)

    assert found is not None
    assert found.name == "After"


async def test_delete_survives_into_a_separate_session(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with committing_sessions() as writing:
        service = ProjectService(writing)
        created = await service.create(ProjectCreate(name="Doomed"))
        await service.delete(created.id)

    async with committing_sessions() as reading:
        assert await reading.get(Project, created.id) is None


async def test_tag_create_survives_into_a_separate_session(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with committing_sessions() as writing:
        created = await TagService(writing).create(TagCreate(name="durable-tag"))

    async with committing_sessions() as reading:
        assert await reading.get(Tag, created.id) is not None


async def test_task_create_survives_into_a_separate_session(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Required by this repo's own postmortem, not by this plan.

    `docs/journals/journal-260921-1645-project-tag-crud-defects.md` closes with
    the rule that every new entity gaining CRUD endpoints needs a cross-session
    durability test, because the ordinary harness cannot see a missing
    `commit()` — a flushed row is visible to the session that wrote it. `Task`
    is such an entity as of this branch.
    """
    async with committing_sessions() as writing:
        project = await ProjectService(writing).create(ProjectCreate(name="Durable holder"))
        created = await TaskService(writing).create(project.id, TaskCreate(title="Durable task"))

    async with committing_sessions() as reading:
        found = await reading.get(Task, created.id)

    assert found is not None, "the task did not outlive the session that wrote it"
    assert found.title == "Durable task"
