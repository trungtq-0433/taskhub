"""Tag endpoints. Routing and shaping only — no business logic."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.schemas.base import Page
from app.schemas.problem import ProblemDetail
from app.schemas.tag import TagCreate, TagRead, TagUpdate
from app.services.tag import TagServiceDep

router = APIRouter(prefix="/tags", tags=["tags"])

ErrorResponses = dict[int | str, dict[str, Any]]

NOT_FOUND: ErrorResponses = {404: {"model": ProblemDetail, "description": "No such tag"}}
CONFLICT: ErrorResponses = {409: {"model": ProblemDetail, "description": "Name already taken"}}

# Bounded, like `size`. Without a ceiling the offset overflows Postgres's
# bigint and the request dies as a 500 instead of being refused as a 422.
PageNumber = Annotated[int, Query(ge=1, le=100_000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("")
async def list_tags(
    service: TagServiceDep, page: PageNumber = 1, size: PageSize = 20
) -> Page[TagRead]:
    items, total = await service.list(page=page, size=size)
    return Page.of(
        [TagRead.model_validate(item) for item in items], total=total, page=page, size=size
    )


@router.get("/{tag_id}", responses=NOT_FOUND)
async def get_tag(tag_id: int, service: TagServiceDep) -> TagRead:
    return TagRead.model_validate(await service.get(tag_id))


@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def create_tag(payload: TagCreate, service: TagServiceDep) -> TagRead:
    return TagRead.model_validate(await service.create(payload))


@router.patch("/{tag_id}", responses={**NOT_FOUND, **CONFLICT})
async def update_tag(tag_id: int, payload: TagUpdate, service: TagServiceDep) -> TagRead:
    return TagRead.model_validate(await service.update(tag_id, payload))


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_tag(tag_id: int, service: TagServiceDep) -> None:
    await service.delete(tag_id)
