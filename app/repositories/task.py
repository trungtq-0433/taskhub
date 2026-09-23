"""Queries against the `task` table. No business rules live here."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.constants import TaskStatus
from app.models import Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, task_id: int) -> Task | None:
        return await self._session.get(Task, task_id)

    async def list_for_project(self, project_id: int, *, offset: int, limit: int) -> Sequence[Task]:
        """One page of a project's tasks, with tags and assignee already loaded.

        The options live here rather than at the call site so a caller cannot
        opt out of them by accident. Under `AsyncSession` that is not a
        performance question: touching an unloaded attribute outside a greenlet
        raises `MissingGreenlet`, so a forgotten option is a 500.

        The two strategies differ because the relationships do. `tags` is a
        collection, and `joinedload` on a collection multiplies rows, forces
        `.unique()` on the result — omit it and SQLAlchemy raises
        `InvalidRequestError` — and drags every parent column across the wire
        once per tag. `assignee` is many-to-one, where a join multiplies
        nothing and costs no extra statement.

        Ordered by `id`, not `created_at`: two tasks written in the same
        transaction share a timestamp to the microsecond, and an unstable sort
        makes pagination drop and repeat rows.
        """
        statement = (
            select(Task)
            .where(Task.project_id == project_id)
            .options(selectinload(Task.tags), joinedload(Task.assignee))
            .order_by(Task.id)
            .offset(offset)
            .limit(limit)
        )
        return (await self._session.scalars(statement)).all()

    async def count_for_project(self, project_id: int) -> int:
        """Serves `ProjectDetail.total_tasks` and the delete pre-check both."""
        total = await self._session.scalar(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
        return total or 0

    async def count_by_status_for_assignee(self, user_id: int) -> dict[str, int]:
        """One GROUP BY, not one COUNT per status.

        Every status the enum knows is present in the result, including the
        ones with no rows, so the caller never branches on a missing key. The
        merge starts from the enum, so a stale value left in the table shows up
        rather than crashing.
        """
        rows = await self._session.execute(
            select(Task.status, func.count())
            .where(Task.assignee_id == user_id)
            .group_by(Task.status)
        )
        counts: dict[str, int] = {status.value: 0 for status in TaskStatus}
        for status, count in rows.all():
            counts[status] = count
        return counts

    async def add(self, task: Task) -> Task:
        """Flush, never commit — see `ProjectRepository.add`."""
        self._session.add(task)
        await self._session.flush()
        return task
