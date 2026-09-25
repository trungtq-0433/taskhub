"""Business rules and transaction boundaries for tasks."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.exceptions import BusinessRuleError
from app.models import Tag, Task, User
from app.repositories.tag import TagRepository
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.schemas.task import TaskCreate
from app.services.project import ProjectService


class TaskService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._tasks = TaskRepository(session)
        self._tags = TagRepository(session)
        self._users = UserRepository(session)
        # Composed rather than reaching for ProjectRepository directly: both
        # routes need "404 if the project does not exist", and ProjectService
        # already owns that answer including its `project-not-found` slug.
        # Re-deriving it is how two endpoints end up 404-ing differently for
        # the same reason.
        self._projects = ProjectService(session)

    async def list_for_project(
        self, project_id: int, *, page: int, size: int
    ) -> tuple[list[Task], int]:
        await self._projects.get(project_id)
        items = await self._tasks.list_for_project(project_id, offset=(page - 1) * size, limit=size)
        return list(items), await self._tasks.count_for_project(project_id)

    async def create(self, project_id: int, payload: TaskCreate) -> Task:
        await self._projects.get(project_id)
        assignee = await self._resolve_assignee(payload.assignee_id)
        tags = await self._resolve_tags(payload.tag_ids)

        task = Task(
            title=payload.title,
            description=payload.description,
            status=payload.status,
            project_id=project_id,
        )
        # The objects, not the ids. The response reads `task.assignee` and
        # `task.tags`, and an unassigned relationship would lazy-load there —
        # which under AsyncSession raises MissingGreenlet rather than issuing a
        # query. Both were already loaded to be validated, so this costs
        # nothing extra, and `expire_on_commit=False` is what lets them survive
        # the commit below.
        task.assignee = assignee
        task.tags = tags

        await self._tasks.add(task)
        await self._session.commit()
        return task

    async def _resolve_assignee(self, assignee_id: int | None) -> User | None:
        if assignee_id is None:
            return None

        user = await self._users.get(assignee_id)
        if user is None:
            raise BusinessRuleError(
                f"No user with id {assignee_id}.", problem_type="assignee-not-found"
            )
        return user

    async def _resolve_tags(self, tag_ids: list[int]) -> list[Tag]:
        """Load every tag at once, and name the ids that do not exist.

        Left to the database this would be an IntegrityError, which the global
        handler renders as a generic 409 — the client would learn that
        something conflicted but not which id was wrong.
        """
        if not tag_ids:
            return []

        tags = list(await self._tags.list_by_ids(tag_ids))
        missing = sorted(set(tag_ids) - {tag.id for tag in tags})
        if missing:
            raise BusinessRuleError(f"No tags with ids {missing}.", problem_type="unknown-tag-ids")
        return tags


async def get_task_service(session: SessionDep) -> TaskService:
    """Built on the event loop — see `get_project_service` for why."""
    return TaskService(session)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
