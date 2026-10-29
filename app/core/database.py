"""Async SQLAlchemy 2.0 engine, session factory and FastAPI session dependency."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import MetaData
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Postgres invents names like `project_name_key` for constraints you do not name,
# and `drop_constraint()` addresses them by name. Without a convention, autogenerate
# emits phantom drop/recreate pairs whenever the reflected name and the metadata name
# disagree about an identical constraint. Free to set now, before any migration
# exists; retrofitting costs one RENAME CONSTRAINT per constraint.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base shared by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_recycle=settings.db_pool_recycle,
    future=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session per request.

    Transaction control belongs to the service layer: services commit
    explicitly. Anything left open is rolled back when the request ends.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close pooled connections — called on application shutdown."""
    await engine.dispose()


def violated_constraint(exc: IntegrityError) -> str | None:
    """The name of the constraint or unique index an `IntegrityError` tripped.

    Read from asyncpg's own exception, which SQLAlchemy's adapter chains as the
    DBAPI error's `__cause__`, rather than searched for in the message text,
    which the driver is free to reword.
    """
    cause = exc.orig.__cause__ if exc.orig is not None else None
    name = getattr(cause, "constraint_name", None)
    return name if isinstance(name, str) else None


SessionDep = Annotated[AsyncSession, Depends(get_session)]
