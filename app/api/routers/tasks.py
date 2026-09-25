"""Task endpoints, nested under a project. Routing and shaping only."""

from fastapi import APIRouter, status

from app.api.params import PaginationDep, not_found
from app.schemas.base import Page
from app.schemas.task import TaskCreate, TaskRead
from app.services.task import TaskServiceDep

# Its own module rather than a section of projects.py: a task is a resource,
# and a router file that carries two of them stops being routing-only.
router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])

# The project named in the path, not the tasks: a project that exists but
# holds none answers 200 with an empty page. Only a project that does not
# exist answers 404 — an empty list there would claim it exists.
PROJECT_NOT_FOUND = not_found("project")


@router.get("", summary="List a project's tasks", responses=PROJECT_NOT_FOUND)
async def list_tasks(
    project_id: int, service: TaskServiceDep, pagination: PaginationDep
) -> Page[TaskRead]:
    """Ordered by id. Each task carries its tags and its assignee.

    Both are loaded eagerly, so the statement count does not grow with the
    number of tasks on the page.
    """
    items, total = await service.list_for_project(
        project_id, page=pagination.page, size=pagination.size
    )
    return Page.of(
        [TaskRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.post(
    "",
    summary="Create a task in a project",
    status_code=status.HTTP_201_CREATED,
    response_description="The task as stored, with its tags and assignee",
    responses=PROJECT_NOT_FOUND,
)
async def create_task(project_id: int, payload: TaskCreate, service: TaskServiceDep) -> TaskRead:
    """`assignee_id` and `tag_ids` must name rows that exist.

    An id that does not answers 422 and names it, rather than failing as a
    constraint violation the client cannot read.
    """
    return TaskRead.model_validate(await service.create(project_id, payload))
