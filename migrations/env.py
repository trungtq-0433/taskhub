"""Alembic environment.

The DSN comes from `app.core.config.settings` — one source of truth, already
validated at import. Pointing migrations somewhere else is done by setting
`DATABASE_URL`, exactly as it is for the application itself; there is no
second mechanism.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import Base

# Side-effect import: registers every model on Base.metadata. Without it
# autogenerate sees an empty metadata and emits a migration that DROPS tables.
import app.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without this a column whose type changed produces no diff at all.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations() -> None:
    """Alembic is written synchronously; the driver here is not.

    `run_sync` bridges the two: it runs `do_run_migrations` in a greenlet that
    hands it a connection which looks synchronous, and yields to the event loop
    underneath whenever that code does I/O.
    """
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # A migration is one command and then exit. The application's pool is
        # machinery it never uses.
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline mode (--sql) is not wired up. Nothing here needs it yet; "
        "add run_migrations_offline() from Alembic's async template if that changes."
    )

asyncio.run(run_migrations())
