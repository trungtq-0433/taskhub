"""Role and ownership guards, layered on top of `ActiveUserDep`.

`verify_admin_role` and `verify_project_manager` are attached to no route
(plan 260928 decision 19): they exist so a later PR can wire them without
inventing the shape. `verify_comment_modifier` is wired to the comment delete
route.

`verify_admin_role` is a role check; `verify_project_manager` is a resource
check and re-fetches the project through `ProjectServiceDep` — the same
session `get_project_service` already cached for this request, so a handler's
own `service.get(project_id)` afterwards would cost no second SELECT. Both
dependencies return the verified caller; a route behind `AdminDep` or
`ProjectManagerDep` that never reads it would bind it as `_admin` / `_manager`.
"""

from typing import Annotated

from fastapi import Depends

from app.api.auth import ActiveUserDep
from app.api.params import IdPath
from app.constants import UserRole
from app.core.exceptions import ForbiddenError
from app.models import Comment, Project, User
from app.services.comment import CommentServiceDep
from app.services.project import ProjectServiceDep


def can_manage_project(user: User, project: Project) -> bool:
    """Owner or admin. Pure: no I/O, testable without HTTP.

    The `is not None` is load-bearing, not decorative: without it, an unsaved
    user whose `id` is still `None` would equal an ownerless project's
    `owner_id` of `None` and "own" it.
    """
    if user.role == UserRole.ADMIN:
        return True
    return project.owner_id is not None and project.owner_id == user.id


def can_modify_comment(user: User, comment: Comment, project: Project) -> bool:
    """The comment's author, or whoever can manage its task's project.

    The `is not None` mirrors `can_manage_project`: a comment whose author was
    deleted has `author_id` of `None`, and an unsaved user's `id` is `None` too.
    """
    if comment.author_id is not None and comment.author_id == user.id:
        return True
    return can_manage_project(user, project)


async def verify_admin_role(user: ActiveUserDep) -> User:
    if user.role != UserRole.ADMIN:
        raise ForbiddenError(
            "This action requires an administrator.", problem_type="admin-required"
        )
    return user


async def verify_project_manager(
    project_id: int, user: ActiveUserDep, projects: ProjectServiceDep
) -> User:
    """404 before 403: a project's existence is already public through
    `GET /projects/{project_id}`, so answering 404 for a missing one here
    leaks nothing a client could not already learn."""
    project = await projects.get(project_id)
    if not can_manage_project(user, project):
        raise ForbiddenError(
            "Only the project's owner or an administrator may do this.",
            problem_type="project-manager-required",
        )
    return user


async def verify_comment_modifier(
    task_id: IdPath, comment_id: IdPath, user: ActiveUserDep, comments: CommentServiceDep
) -> Comment:
    """404 before 403, so a caller who may not delete learns nothing about a
    comment under another task. Returns the verified comment."""
    comment, project = await comments.get_with_project(task_id, comment_id)
    if not can_modify_comment(user, comment, project):
        raise ForbiddenError(
            "Only the comment's author, an administrator or the project's owner may do this.",
            problem_type="comment-forbidden",
        )
    return comment


AdminDep = Annotated[User, Depends(verify_admin_role)]
ProjectManagerDep = Annotated[User, Depends(verify_project_manager)]
CommentModifierDep = Annotated[Comment, Depends(verify_comment_modifier)]
