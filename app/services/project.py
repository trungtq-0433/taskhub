"""Business rules and transaction boundaries for projects."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Project
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._projects = ProjectRepository(session)

    async def get(self, project_id: int) -> Project:
        project = await self._projects.get(project_id)
        if project is None:
            raise NotFoundError(
                f"Project {project_id} does not exist.", problem_type="project-not-found"
            )
        return project

    async def list(self, *, page: int, size: int) -> tuple[list[Project], int]:
        items = await self._projects.list(offset=(page - 1) * size, limit=size)
        return list(items), await self._projects.count()

    async def create(self, payload: ProjectCreate) -> Project:
        await self._reject_duplicate_name(payload.name)

        project = await self._projects.add(Project(**payload.model_dump()))
        await self._session.commit()
        return project

    async def update(self, project_id: int, payload: ProjectUpdate) -> Project:
        project = await self.get(project_id)

        # exclude_unset is the difference between "leave this alone" and "null
        # it": a plain model_dump() would set every field the client omitted.
        changes = payload.model_dump(exclude_unset=True)

        if "name" in changes:
            await self._reject_duplicate_name(changes["name"], exclude_id=project_id)

        for field, value in changes.items():
            setattr(project, field, value)

        await self._session.commit()
        return project

    async def delete(self, project_id: int) -> None:
        project = await self.get(project_id)
        await self._projects.delete(project)
        await self._session.commit()

    async def _reject_duplicate_name(self, name: str, *, exclude_id: int | None = None) -> None:
        """Check first, so the client gets a code it can branch on.

        This races two concurrent requests. The unique constraint is the real
        guard — losing the race raises IntegrityError, which the global handler
        already answers as a 409 rather than a 500. This check buys the
        specific problem type, not the correctness.
        """
        if await self._projects.name_exists(name, exclude_id=exclude_id):
            raise ConflictError(
                f"A project named {name!r} already exists.",
                problem_type="duplicate-project-name",
            )


ProjectServiceDep = Annotated[ProjectService, Depends()]
