"""Queries against the `task` table. No business rules live here."""

from typing import cast

from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.constants import TaskStatus
from app.models import Task
from app.schemas.task import TaskFilter


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def paginate(
        self, task_filter: TaskFilter | None, *, project_id: int | None, params: Params
    ) -> Page[Task]:
        """One page of tasks, with tags and assignee already loaded.

        `project_id` is the nested route's path segment, not a query filter —
        it is applied as its own `WHERE` here rather than folded into
        `TaskFilter`, so a filter DTO built from query params alone can never
        widen or narrow it by accident. `project_id=None` is `GET /tasks`: no
        `WHERE` on it at all, which is what lets that route span every
        project. `task_filter=None` is the nested route: it takes no
        status/priority filters, so there is nothing to apply.

        `apaginate` builds its own count query from this same statement
        (`subquery_count`, the default), so `page.total` and `page.items` can
        never disagree about which rows matched.

        The options live here rather than at the call site so a caller cannot
        opt out of them by accident. Under `AsyncSession` that is not a
        performance question: touching an unloaded attribute outside a
        greenlet raises `MissingGreenlet`, so a forgotten option is a 500.

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
            .options(selectinload(Task.tags), joinedload(Task.assignee))
            .order_by(Task.id)
        )
        if project_id is not None:
            statement = statement.where(Task.project_id == project_id)
        if task_filter is not None:
            statement = task_filter.filter(statement)
        # `apaginate` is typed to return `Any` (it is generic over whatever
        # page/item type a caller wants, resolved at the call site rather than
        # in its own signature) — `cast` states the type this call site
        # actually gets back, a `Page` of the ORM rows the statement above
        # selects, without importing `Any` into this module's own contract.
        return cast(Page[Task], await apaginate(self._session, statement, params))

    async def get(self, task_id: int) -> Task | None:
        return await self._session.get(Task, task_id)

    async def count_for_project(self, project_id: int) -> int:
        """Serves `ProjectDetail.total_tasks` and the delete pre-check both."""
        total = await self._session.scalar(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
        return total or 0

    async def count_by_status_for_assignee(self, user_id: int) -> dict[str, int]:
        """One GROUP BY, not one COUNT per status.

        Every status the enum knows is present in the result, including the
        ones with no rows, so the caller never branches on a missing key.

        A value the enum no longer knows comes back too, and this dict is the
        last place it survives: `TaskCounts` drops it, because `BaseSchema`
        sets `extra="ignore"`, and the tasks holding it then vanish from the
        profile with no error and no `total` to check the sum against.
        `UserService.get_profile` logs when that happens — without the log it
        is silent. The column is VARCHAR precisely so the status set can change
        without a migration, which makes a stale value an expected state rather
        than a curiosity.
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
