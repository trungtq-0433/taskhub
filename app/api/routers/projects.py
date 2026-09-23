"""Project endpoints. Routing and shaping only — no business logic."""

from fastapi import APIRouter, status

from app.api.params import CONFLICT, PaginationDep, not_found
from app.schemas.base import Page
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project import ProjectServiceDep

router = APIRouter(prefix="/projects", tags=["projects"])

NOT_FOUND = not_found("project")


@router.get("", summary="List projects")
async def list_projects(service: ProjectServiceDep, pagination: PaginationDep) -> Page[ProjectRead]:
    """Ordered by name. `total` counts every match, not just this page."""
    items, total = await service.list(page=pagination.page, size=pagination.size)
    return Page.of(
        [ProjectRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.get("/{project_id}", summary="Fetch one project", responses=NOT_FOUND)
async def get_project(project_id: int, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(await service.get(project_id))


@router.post(
    "",
    summary="Create a project",
    status_code=status.HTTP_201_CREATED,
    response_description="The project as stored, with its id and timestamps",
    responses=CONFLICT,
)
async def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    """`name` must be unique; a clash answers 409 rather than 422."""
    return ProjectRead.model_validate(await service.create(payload))


@router.patch(
    "/{project_id}",
    summary="Update part of a project",
    responses={**NOT_FOUND, **CONFLICT},
)
async def update_project(
    project_id: int, payload: ProjectUpdate, service: ProjectServiceDep
) -> ProjectRead:
    """Only the fields present in the body change.

    Omitting a field leaves it as it was. Sending `null` is a different
    request — store null — which is refused for `name` and `status` because
    their columns are NOT NULL, and honoured for `description`, which is
    nullable and has no other way to be cleared.
    """
    return ProjectRead.model_validate(await service.update(project_id, payload))


@router.delete(
    "/{project_id}",
    summary="Delete a project",
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="Deleted; no body",
    responses=NOT_FOUND,
)
async def delete_project(project_id: int, service: ProjectServiceDep) -> None:
    """Permanent — there is no soft delete and no undo."""
    await service.delete(project_id)
