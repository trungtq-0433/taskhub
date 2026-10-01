"""Writes to `task_assignment`. No business rules live here.

A Core table, not an ORM model — see `app/models/task_assignment.py` — so this
repository reaches it through `insert`, the way `bookmark.py` does.
"""

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import task_assignment


class TaskAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        task_id: int,
        previous_assignee_id: int | None,
        assignee_id: int,
        assigned_by_id: int,
    ) -> None:
        """Insert one history row. A Core `insert` runs when executed, so an FK
        violation (a user deleted mid-request) is raised inside the caller's
        own `try`."""
        await self._session.execute(
            insert(task_assignment).values(
                task_id=task_id,
                previous_assignee_id=previous_assignee_id,
                assignee_id=assignee_id,
                assigned_by_id=assigned_by_id,
            )
        )
