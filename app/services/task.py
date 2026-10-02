"""Business rules and transaction boundaries for tasks."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from fastapi_pagination import Page, Params
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionDep
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)
from app.models import Tag, Task, User
from app.repositories.bookmark import BookmarkRepository, BookmarkRow
from app.repositories.tag import TagRepository
from app.repositories.task import TaskRepository
from app.repositories.task_assignment import TaskAssignmentRepository
from app.repositories.user import UserRepository
from app.schemas.task import TaskCreate, TaskFilter
from app.services.project import ProjectService


class TaskService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._tasks = TaskRepository(session)
        self._tags = TagRepository(session)
        self._users = UserRepository(session)
        self._bookmarks = BookmarkRepository(session)
        self._assignments = TaskAssignmentRepository(session)
        # Composed rather than reaching for ProjectRepository directly: both
        # routes need "404 if the project does not exist", and ProjectService
        # already owns that answer including its `project-not-found` slug.
        # Re-deriving it is how two endpoints end up 404-ing differently for
        # the same reason.
        self._projects = ProjectService(session)

    async def list(
        self,
        *,
        project_id: int | None = None,
        task_filter: TaskFilter | None = None,
        params: Params,
    ) -> Page[Task]:
        """One page of tasks, paginated by fastapi-pagination.

        `project_id=None` is `GET /tasks`: no project in the path, so no 404
        to answer. `task_filter` is only ever set for that same route — the
        nested route takes no status/priority filters, so it never builds one.
        """
        if project_id is not None:
            await self._projects.get(project_id)  # nested route: missing project = 404, not []
        return await self._tasks.paginate(task_filter, project_id=project_id, params=params)

    async def get(self, task_id: int, *, for_update: bool = False) -> Task:
        task = await (self._tasks.get_for_update if for_update else self._tasks.get)(task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} does not exist.", problem_type="task-not-found")
        return task

    async def create(self, project_id: int, payload: TaskCreate) -> Task:
        await self._projects.get(project_id)
        assignee = await self._resolve_assignee(payload.assignee_id)
        tags = await self._resolve_tags(payload.tag_ids)

        task = Task(
            title=payload.title,
            description=payload.description,
            status=payload.status,
            priority=payload.priority,
            project_id=project_id,
        )
        # The objects, not the ids. The response reads `task.assignee` and
        # `task.tags`, and an unassigned relationship would lazy-load there —
        # which under AsyncSession raises MissingGreenlet rather than issuing a
        # query. Both were already loaded to be validated, so this costs
        # nothing extra, and `expire_on_commit=False` is what lets them survive
        # the commit below.
        task.assignee = assignee
        task.tags = list(tags)

        await self._tasks.add(task)
        await self._session.commit()
        return task

    async def bookmark(self, task_id: int, *, user_id: int) -> BookmarkRow:
        """First call -> 201; the same user on the same task again -> 409
        (not idempotent).
        """
        await self.get(task_id)
        if await self._bookmarks.exists(user_id=user_id, task_id=task_id):
            raise ConflictError(
                f"User {user_id} already bookmarked task {task_id}.",
                problem_type="already-bookmarked",
            )
        try:
            row = await self._bookmarks.add(user_id=user_id, task_id=task_id)
            await self._session.commit()
        except IntegrityError as exc:
            # The composite primary key is the real guard, same as
            # `AuthService.register`: two requests can both pass the `exists`
            # check above before either commits, and only one insert wins the
            # race. A task deleted mid-request would also land here, and
            # nothing deletes tasks today.
            raise ConflictError(
                f"User {user_id} already bookmarked task {task_id}.",
                problem_type="already-bookmarked",
            ) from exc
        return row

    async def assign(self, task_id: int, *, assignee_id: int, assigned_by_id: int) -> Task:
        """Lock, compare, write, record, load the response, commit last.

        The response is built under the lock, never re-read after it. See
        `docs/database.md` for the lock mode and the ordering.
        """
        task = await self.get(task_id, for_update=True)
        try:
            if task.assignee_id != assignee_id:  # unchanged: 200, no history
                assignee = await self._get_assignee(assignee_id)
                if not assignee.is_active:
                    raise BusinessRuleError(
                        f"User {assignee_id} is disabled.", problem_type="assignee-inactive"
                    )
                task.assignee = assignee
                await self._session.flush()  # autoflush is off: UPDATE before the INSERT
                await self._assignments.add(
                    task_id=task_id,
                    assignee_id=assignee_id,
                    assigned_by_id=assigned_by_id,
                )
            await self._session.refresh(task, ["assignee", "tags"])
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            cause = exc.orig.__cause__ if exc.orig is not None else None
            constraint_name = getattr(cause, "constraint_name", None)
            if constraint_name == "fk_task_assignment_assigned_by_id_user":
                raise UnauthorizedError("Could not validate credentials.") from exc

            # The assignee was deleted between the lookup and the write; the
            # FK says so at the flush or the history insert.
            raise BusinessRuleError(
                f"No user with id {assignee_id}.", problem_type="assignee-not-found"
            ) from exc
        return task

    async def _resolve_assignee(self, assignee_id: int | None) -> User | None:
        if assignee_id is None:
            return None
        return await self._get_assignee(assignee_id)

    async def _get_assignee(self, assignee_id: int) -> User:
        user = await self._users.get(assignee_id)
        if user is None:
            raise BusinessRuleError(
                f"No user with id {assignee_id}.", problem_type="assignee-not-found"
            )
        return user

    async def _resolve_tags(self, tag_ids: Sequence[int]) -> Sequence[Tag]:
        """Load every tag at once, and name the ids that do not exist.

        Left to the database this would be an IntegrityError, which the global
        handler renders as a generic 409 — the client would learn that
        something conflicted but not which id was wrong.

        Typed as `Sequence`, not the bare `list[...]` the original wrote: this
        class now has a method named `list`, and a plain `list[int]`
        annotation on a method defined after it resolves against that method
        object instead of the builtin — a real `TypeError` at import time, not
        a style nit. Calling `list(...)` inside a method *body* stays safe;
        only a bare annotation written directly in the class's execution order
        is affected.
        """
        if not tag_ids:
            return []

        tags = await self._tags.list_by_ids(tag_ids)
        missing = sorted(set(tag_ids) - {tag.id for tag in tags})
        if missing:
            raise BusinessRuleError(f"No tags with ids {missing}.", problem_type="unknown-tag-ids")
        return tags


async def get_task_service(session: SessionDep) -> TaskService:
    """Built on the event loop — see `get_project_service` for why."""
    return TaskService(session)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
