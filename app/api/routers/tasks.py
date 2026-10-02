"""Task endpoints: nested list/create, the top-level list, the bookmark and assign.

One module rather than one file per route: the nested route's prefix is
dropped so the top-level `/tasks` and `/tasks/{task_id}/bookmark` can sit
beside it under the same `tags=["tasks"]`.
"""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_filter import FilterDepends
from fastapi_pagination import Page as LibraryPage

from app.api.auth import ActiveUserDep
from app.api.params import (
    INACTIVE_USER,
    TASK_NOT_FOUND,
    UNAUTHORIZED,
    BoundedParams,
    ErrorResponses,
    IdPath,
    not_found,
)
from app.core.handlers import PROBLEM_CONTENT
from app.schemas.task import BookmarkRead, TaskAssign, TaskCreate, TaskFilter, TaskRead
from app.services.task import TaskServiceDep

router = APIRouter(tags=["tasks"])

# The project named in the path, not the tasks: a project that exists but
# holds none answers 200 with an empty page. Only a project that does not
# exist answers 404 — an empty list there would claim it exists.
PROJECT_NOT_FOUND = not_found("project")
ALREADY_BOOKMARKED: ErrorResponses = {
    409: {"content": PROBLEM_CONTENT, "description": "Already bookmarked by this user"}
}


# The handler docstrings below are published as each operation's description in
# /docs, so they say only what a client needs. For maintainers: `params` and
# `task_filter` are fastapi-pagination's and fastapi-filter's own dependencies,
# not this app's in-house `PaginationDep`/`Page[T]`; `params` is
# `BoundedParams` from app/api/params.py, which holds `page` and `size` to the
# same bounds as every other list route (default `size` 50 here). The
# per-field "case-insensitive" note has to live in the `GET /tasks`
# docstring: `FilterDepends` hands FastAPI a model class, whose signature
# carries no field descriptions into OpenAPI (fastapi-pagination's own `Params`
# loses its "Page number" description the same way). The repository shapes the
# ORM rows; each handler is the one place that turns them into `TaskRead`.


@router.get("/tasks", summary="List tasks across every project")
async def list_all_tasks(
    service: TaskServiceDep,
    params: Annotated[BoundedParams, Depends()],
    task_filter: TaskFilter = FilterDepends(TaskFilter),
) -> LibraryPage[TaskRead]:
    """Ordered by id; each task carries its tags and its assignee.

    `status` and `priority` are case-insensitive (`TODO` matches `todo`) and
    combine with AND. `page` goes up to 100,000; `size` defaults to 50, at most 100.
    """
    page = await service.list(task_filter=task_filter, params=params)
    return LibraryPage[TaskRead].create(
        items=[TaskRead.model_validate(item) for item in page.items],
        params=params,
        total=page.total,
    )


@router.get(
    "/projects/{project_id}/tasks", summary="List a project's tasks", responses=PROJECT_NOT_FOUND
)
async def list_tasks(
    project_id: int, service: TaskServiceDep, params: Annotated[BoundedParams, Depends()]
) -> LibraryPage[TaskRead]:
    """Ordered by id; each task carries its tags and its assignee.

    `page` goes up to 100,000; `size` defaults to 50, at most 100. A project
    that does not exist answers 404, not an empty page. This route takes no
    `status`/`priority` filters — those are `GET /tasks` only.
    """
    # `project_id` is applied as its own `WHERE` in the repository. Tags and
    # assignee are eager-loaded there, so the statement count does not grow
    # with the page.
    page = await service.list(project_id=project_id, params=params)
    return LibraryPage[TaskRead].create(
        items=[TaskRead.model_validate(item) for item in page.items],
        params=params,
        total=page.total,
    )


@router.post(
    "/projects/{project_id}/tasks",
    summary="Create a task in a project",
    status_code=HTTPStatus.CREATED,
    response_description="The task as stored, with its tags and assignee",
    responses=PROJECT_NOT_FOUND,
)
async def create_task(project_id: int, payload: TaskCreate, service: TaskServiceDep) -> TaskRead:
    """`assignee_id` and `tag_ids` must name rows that exist.

    An id that does not answers 422 and names it, rather than failing as a
    constraint violation the client cannot read. `priority` defaults to
    `medium` when omitted.
    """
    return TaskRead.model_validate(await service.create(project_id, payload))


@router.post(
    "/tasks/{task_id}/bookmark",
    summary="Bookmark a task",
    status_code=HTTPStatus.CREATED,
    responses={**UNAUTHORIZED, **INACTIVE_USER, **TASK_NOT_FOUND, **ALREADY_BOOKMARKED},
)
async def bookmark_task(
    task_id: int,
    user: ActiveUserDep,
    service: TaskServiceDep,
) -> BookmarkRead:
    """Logged-in, active users only — a disabled account gets 403, not a
    silent pass. Not idempotent: bookmarking the same task twice is a 409,
    not a silent no-op.

    `user_id` comes only from the token, never from the path or the body, so
    a caller cannot bookmark on someone else's behalf.
    """
    return BookmarkRead.model_validate(await service.bookmark(task_id, user_id=user.id))


@router.post(
    "/tasks/{task_id}/assign",
    summary="Assign a task to a user",
    responses={**UNAUTHORIZED, **INACTIVE_USER, **TASK_NOT_FOUND},
)
async def assign_task(
    task_id: IdPath,
    payload: TaskAssign,
    user: ActiveUserDep,
    service: TaskServiceDep,
) -> TaskRead:
    """Any active user may assign any task to any active user, themselves
    included. Assigning the current assignee again is a 200 no-op. There is no
    unassign: `assignee_id` is required.
    """
    return TaskRead.model_validate(
        await service.assign(task_id, assignee_id=payload.assignee_id, assigned_by_id=user.id)
    )
