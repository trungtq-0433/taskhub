"""Queries against the `project` table. No business rules live here."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: int) -> Project | None:
        return await self._session.get(Project, project_id)

    async def list(self, *, offset: int, limit: int) -> Sequence[Project]:
        statement = select(Project).order_by(Project.name).offset(offset).limit(limit)
        return (await self._session.scalars(statement)).all()

    async def count(self) -> int:
        """Counted in the database.

        `len(await self.list(...))` would load every row to count them, and
        would be wrong anyway — `list` returns one page, not the whole table.
        """
        total = await self._session.scalar(select(func.count()).select_from(Project))
        return total or 0

    async def add(self, project: Project) -> Project:
        """Flush, never commit.

        The flush assigns the primary key so the caller can read it. Committing
        would take the transaction boundary away from the service, which is the
        only layer that knows whether the whole operation succeeded.
        """
        self._session.add(project)
        await self._session.flush()
        return project

    async def delete(self, project: Project) -> None:
        await self._session.delete(project)
        await self._session.flush()

    async def name_exists(self, name: str, *, exclude_id: int | None = None) -> bool:
        """Whether another project already holds this name.

        `exclude_id` is for updates: renaming a project to the name it already
        has must not be reported as a clash with itself.
        """
        statement = select(Project.id).where(Project.name == name)
        if exclude_id is not None:
            statement = statement.where(Project.id != exclude_id)
        return await self._session.scalar(statement.limit(1)) is not None
