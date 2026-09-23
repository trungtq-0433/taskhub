"""Tag endpoints. Routing and shaping only — no business logic."""

from fastapi import APIRouter, status

from app.api.params import CONFLICT, PaginationDep, not_found
from app.schemas.base import Page
from app.schemas.tag import TagCreate, TagRead, TagUpdate
from app.services.tag import TagServiceDep

router = APIRouter(prefix="/tags", tags=["tags"])

NOT_FOUND = not_found("tag")


@router.get("", summary="List tags")
async def list_tags(service: TagServiceDep, pagination: PaginationDep) -> Page[TagRead]:
    """Ordered by name. `total` counts every match, not just this page."""
    items, total = await service.list(page=pagination.page, size=pagination.size)
    return Page.of(
        [TagRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.get("/{tag_id}", summary="Fetch one tag", responses=NOT_FOUND)
async def get_tag(tag_id: int, service: TagServiceDep) -> TagRead:
    return TagRead.model_validate(await service.get(tag_id))


@router.post(
    "",
    summary="Create a tag",
    status_code=status.HTTP_201_CREATED,
    response_description="The tag as stored, with its id and timestamps",
    responses=CONFLICT,
)
async def create_tag(payload: TagCreate, service: TagServiceDep) -> TagRead:
    """`name` must be unique. `color` is optional and must be `#RRGGBB`."""
    return TagRead.model_validate(await service.create(payload))


@router.patch("/{tag_id}", summary="Update part of a tag", responses={**NOT_FOUND, **CONFLICT})
async def update_tag(tag_id: int, payload: TagUpdate, service: TagServiceDep) -> TagRead:
    """Only the fields present in the body change.

    Omitting a field leaves it alone. Sending `null` is refused for `name`,
    whose column is NOT NULL, and honoured for `color`, which is nullable —
    that is how a colour gets cleared.
    """
    return TagRead.model_validate(await service.update(tag_id, payload))


@router.delete(
    "/{tag_id}",
    summary="Delete a tag",
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="Deleted; no body",
    responses=NOT_FOUND,
)
async def delete_tag(tag_id: int, service: TagServiceDep) -> None:
    """Permanent — there is no soft delete and no undo."""
    await service.delete(tag_id)
