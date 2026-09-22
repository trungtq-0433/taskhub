"""Test database: where it lives, how it gets created, how it gets its schema.

Tests run against a real Postgres, never a mock. The foundation already shipped
a bug that only a real connection exposed — asyncpg raises `OSError` for an
unreachable database, which `except SQLAlchemyError` does not catch — and a
mocked driver would have kept that test green.
"""

import os
import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def database_url_for_tests() -> str:
    """The dev DSN with `_test` appended to the database name.

    Deliberately not named `test_*`: pytest collects anything so named as a
    test case, and this is a helper.

    `TEST_DATABASE_URL` overrides it outright, for a CI service or a second
    Postgres. The derived default means a fresh clone runs `pytest` with no
    setup ritual.
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override

    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def assert_not_the_dev_database(url: str) -> None:
    """Refuse to touch the database the developer is working in.

    `upgrade head` is destructive against a database whose state is behind, and
    the whole harness runs it on every session. Getting this wrong once costs
    someone their local data.
    """
    target = make_url(url).database
    if target == make_url(settings.database_url).database:
        raise RuntimeError(
            f"Refusing to run tests against the development database "
            f"({target!r}). Set TEST_DATABASE_URL to something else."
        )


async def create_database_if_absent(url: str) -> None:
    """`CREATE DATABASE` if it is not there yet.

    Connects to the `postgres` maintenance database because you cannot create a
    database from inside itself, and in AUTOCOMMIT because Postgres forbids
    CREATE DATABASE inside a transaction block.
    """
    target = make_url(url)
    admin_url = target.set(database="postgres").render_as_string(hide_password=False)

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                # Identifier, so it cannot be a bind parameter. The name is
                # derived from our own settings, not from user input.
                await connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await engine.dispose()


def migrate(url: str) -> None:
    """Bring the test database up to head by running the real migrations.

    Deliberately not `Base.metadata.create_all`: that builds the schema straight
    from the model classes and never executes a migration, so it cannot catch
    the case this suite most needs to catch — a model changed and nobody
    generated the migration.

    Run as a subprocess with DATABASE_URL set, which is the same mechanism
    production uses. The alternative — driving Alembic in-process — means
    teaching env.py about a second source for the DSN, and it cannot be called
    from inside a running event loop because env.py calls asyncio.run().
    """
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
    )
