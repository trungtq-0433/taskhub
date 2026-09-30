"""Role and ownership guards, layered on top of `ActiveUserDep`.

Written per the brief but attached to no route in this PR (decision 19): the
"no other endpoint changes" rule from the scope reset still holds. They exist
so a later PR can wire them without inventing the shape.

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
from app.constants import UserRole
from app.core.exceptions import ForbiddenError
from app.models import Project, User
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


AdminDep = Annotated[User, Depends(verify_admin_role)]
ProjectManagerDep = Annotated[User, Depends(verify_project_manager)]
