"""Business rules and transaction boundaries for comments.

Who may delete a comment is decided at the API layer
(`app.api.permissions.verify_comment_modifier`), not here: a service raises no
`ForbiddenError`.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.exceptions import NotFoundError
from app.models import Comment, Project, User
from app.repositories.comment import CommentRepository
from app.schemas.comment import CommentCreate
from app.services.project import ProjectService
from app.services.task import TaskService


class CommentService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._comments = CommentRepository(session)
        # Composed so each 404 keeps its one owner and its one slug.
        self._tasks = TaskService(session)
        self._projects = ProjectService(session)

    async def create(self, task_id: int, payload: CommentCreate, *, author: User) -> Comment:
        await self._tasks.get(task_id)
        comment = Comment(task_id=task_id, content=payload.content)
        # The object, not `author_id`: the response reads `comment.author`, and
        # an unset relationship would lazy-load there — `MissingGreenlet` under
        # AsyncSession.
        comment.author = author
        await self._comments.add(comment)
        await self._session.commit()
        return comment

    async def get_with_project(self, task_id: int, comment_id: int) -> tuple[Comment, Project]:
        """404 `task-not-found`, then 404 `comment-not-found` (also for a
        comment that belongs to another task), then the task's project."""
        task = await self._tasks.get(task_id)
        comment = await self._comments.get(comment_id)
        if comment is None or comment.task_id != task_id:
            raise self._not_found(task_id, comment_id)
        return comment, await self._projects.get(task.project_id)

    async def delete(self, *, task_id: int, comment_id: int) -> None:
        if not await self._comments.delete(comment_id=comment_id, task_id=task_id):
            raise self._not_found(task_id, comment_id)  # lost a race with another delete
        await self._session.commit()

    @staticmethod
    def _not_found(task_id: int, comment_id: int) -> NotFoundError:
        return NotFoundError(
            f"Comment {comment_id} does not exist on task {task_id}.",
            problem_type="comment-not-found",
        )


async def get_comment_service(session: SessionDep) -> CommentService:
    """Built on the event loop — see `get_project_service` for why."""
    return CommentService(session)


CommentServiceDep = Annotated[CommentService, Depends(get_comment_service)]
