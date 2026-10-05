"""Business rules and transaction boundaries for comments.

Who may delete a comment is decided at the API layer
(`app.api.permissions.verify_comment_modifier`), not here: a service raises no
`ForbiddenError`.

A new comment emails the task's assignee, and nobody else, unless that is the
author, has no address or is disabled. The message is built before the response
is returned: the background task runs after the request's session is closed, so
it is handed plain values, never an ORM object.
"""

from typing import Annotated

from fastapi import BackgroundTasks, Depends

from app.core.database import SessionDep
from app.core.exceptions import NotFoundError
from app.core.mail import Mailer, MailerDep, OutgoingEmail
from app.models import Comment, Project, Task, User
from app.repositories.comment import CommentRepository
from app.repositories.user import UserRepository
from app.schemas.comment import CommentCreate
from app.services.project import ProjectService, ProjectServiceDep
from app.services.task import TaskService, TaskServiceDep


class CommentService:
    def __init__(
        self,
        session: SessionDep,
        *,
        tasks: TaskService,
        projects: ProjectService,
        background_tasks: BackgroundTasks | None = None,
        mailer: Mailer | None = None,
    ) -> None:
        self._session = session
        self._comments = CommentRepository(session)
        self._users = UserRepository(session)
        # Either one `None` means no notification (the delete path never sends).
        self._background_tasks = background_tasks
        self._mailer = mailer
        # Composed so each 404 keeps its one owner and its one slug.
        self._tasks = tasks
        self._projects = projects

    async def create(self, task_id: int, payload: CommentCreate, *, author: User) -> Comment:
        task = await self._tasks.get(task_id)
        comment = Comment(task_id=task_id, content=payload.content)
        # The object, not `author_id`: the response reads `comment.author`, and
        # an unset relationship would lazy-load there — `MissingGreenlet` under
        # AsyncSession.
        comment.author = author
        await self._comments.add(comment)
        # Read in the same transaction as the insert; queued only once it is durable.
        email = await self._notification_for(task, comment, author)
        await self._session.commit()
        if email is not None and self._background_tasks is not None and self._mailer is not None:
            self._background_tasks.add_task(self._mailer.send, email)
        return comment

    async def _notification_for(
        self, task: Task, comment: Comment, author: User
    ) -> OutgoingEmail | None:
        """The email for the task's assignee, or `None` when nobody is to be told.

        Cheap checks first: at most one query, and none when mail is off or the
        task has no one else assigned. The relationship `task.assignee` is never
        touched — it is not loaded and would raise `MissingGreenlet`.
        """
        if self._mailer is None or self._background_tasks is None:
            return None
        if task.assignee_id is None or task.assignee_id == author.id:
            return None
        assignee = await self._users.get(task.assignee_id)
        if assignee is None or not assignee.is_active or assignee.email is None:
            return None
        return OutgoingEmail(
            to=assignee.email,
            # Ids only: client text (a title may hold CR/LF) must stay out of headers.
            subject=f"[TaskHub] New comment on task #{task.id}",
            body=(
                f'{author.username} commented on task #{task.id} "{task.title}":\n\n'
                f"{comment.content}"
            ),
            reference=f"task {task.id}, comment {comment.id}",
        )

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


async def get_comment_service(
    session: SessionDep,
    tasks: TaskServiceDep,
    projects: ProjectServiceDep,
    background_tasks: BackgroundTasks,
    mailer: MailerDep,
) -> CommentService:
    """Built on the event loop — see `get_project_service` for why.

    `background_tasks` is the request's own instance, the one that runs after
    the response is sent.
    """
    return CommentService(
        session, tasks=tasks, projects=projects, background_tasks=background_tasks, mailer=mailer
    )


CommentServiceDep = Annotated[CommentService, Depends(get_comment_service)]
