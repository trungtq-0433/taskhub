"""Queries against `task_bookmark`. No business rules live here.

A Core table, not an ORM model — see `app/models/task_bookmark.py` for why —
so this repository reaches it through `insert`/`select` rather than
`session.add`.
"""

from datetime import datetime

from sqlalchemy import Row, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import task_bookmark

# What `add` hands back: exactly the two columns its `.returning()` names,
# in that order — the shape `BookmarkRead.model_validate` reads.
BookmarkRow = Row[tuple[int, datetime]]


class BookmarkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, *, user_id: int, task_id: int) -> bool:
        """The pre-check behind the specific 409 — see `TaskService.bookmark`."""
        statement = select(1).where(
            task_bookmark.c.user_id == user_id, task_bookmark.c.task_id == task_id
        )
        return await self._session.scalar(statement) is not None

    async def add(self, *, user_id: int, task_id: int) -> BookmarkRow:
        """Insert the bookmark and hand back what `BookmarkRead` needs.

        A Core `insert` runs when executed, not when the session later
        flushes — so the `IntegrityError` from a lost race against the
        composite primary key is raised inside the caller's own `try`, exactly
        where `TaskService.bookmark` expects to catch it.
        """
        statement = (
            insert(task_bookmark)
            .values(user_id=user_id, task_id=task_id)
            .returning(task_bookmark.c.task_id, task_bookmark.c.created_at)
        )
        result = await self._session.execute(statement)
        return result.one()
