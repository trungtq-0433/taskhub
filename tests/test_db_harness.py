"""Proof that the harness isolates tests from each other.

These assert about the fixtures themselves rather than about application code.
If they ever fail, every other database test in the suite is unreliable —
passing for the wrong reason, or failing because of what ran before them.
"""

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Project, Tag
from tests.db import database_url_for_tests

SHARED_NAME = "the same name in two tests"


def test_the_harness_never_points_at_the_development_database() -> None:
    assert make_url(database_url_for_tests()).database != make_url(settings.database_url).database


async def test_schema_exists_because_migrations_ran(db_session: AsyncSession) -> None:
    """A query against both tables proves `upgrade head` reached this database."""
    assert await db_session.scalar(select(func.count()).select_from(Project)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Tag)) == 0


async def test_writes_a_row_and_commits(db_session: AsyncSession) -> None:
    """Commits, like a service does. The next test proves it still rolled back."""
    db_session.add(Tag(name=SHARED_NAME))
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(Tag)) == 1


async def test_the_committed_row_is_gone(db_session: AsyncSession) -> None:
    """Same unique name as the previous test.

    A duplicate-key error here means the commit above survived, and the
    savepoint mode is not doing its job. An empty table means it is.
    """
    assert await db_session.scalar(select(func.count()).select_from(Tag)) == 0

    db_session.add(Tag(name=SHARED_NAME))
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(Tag)) == 1
