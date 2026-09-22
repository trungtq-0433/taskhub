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

from app.models import Project, Tag
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.tag import TagCreate
from app.services.project import ProjectService
from app.services.tag import TagService


@pytest.fixture
async def committing_sessions(
    _engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Real sessions that really commit, with the tables emptied afterwards."""
    factory = async_sessionmaker(bind=_engine, expire_on_commit=False)
    yield factory

    async with factory() as cleanup:
        await cleanup.execute(delete(Project))
        await cleanup.execute(delete(Tag))
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
