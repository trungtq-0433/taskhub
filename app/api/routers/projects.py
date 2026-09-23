"""Project endpoints. Routing and shaping only — no business logic."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.core.handlers import PROBLEM_CONTENT
from app.schemas.base import Page
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project import ProjectServiceDep

router = APIRouter(prefix="/projects", tags=["projects"])

# DEFAULT_ERROR_RESPONSES covers 422 and 500 app-wide; anything else is
# per-route, or the schema understates what a client has to handle.
ErrorResponses = dict[int | str, dict[str, Any]]

NOT_FOUND: ErrorResponses = {404: {"content": PROBLEM_CONTENT, "description": "No such project"}}
CONFLICT: ErrorResponses = {409: {"content": PROBLEM_CONTENT, "description": "Name already taken"}}

# Bounded, like `size`. Without a ceiling the offset overflows Postgres's
# bigint and the request dies as a 500 instead of being refused as a 422.
PageNumber = Annotated[int, Query(ge=1, le=100_000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("")
async def list_projects(
    service: ProjectServiceDep, page: PageNumber = 1, size: PageSize = 20
) -> Page[ProjectRead]:
    items, total = await service.list(page=page, size=size)
    return Page.of(
        [ProjectRead.model_validate(item) for item in items], total=total, page=page, size=size
    )


@router.get("/{project_id}", responses=NOT_FOUND)
async def get_project(project_id: int, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(await service.get(project_id))


@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(await service.create(payload))


@router.patch("/{project_id}", responses={**NOT_FOUND, **CONFLICT})
async def update_project(
    project_id: int, payload: ProjectUpdate, service: ProjectServiceDep
) -> ProjectRead:
    return ProjectRead.model_validate(await service.update(project_id, payload))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_project(project_id: int, service: ProjectServiceDep) -> None:
    await service.delete(project_id)
