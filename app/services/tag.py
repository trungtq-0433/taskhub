"""Business rules and transaction boundaries for tags."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Tag
from app.repositories.tag import TagRepository
from app.schemas.base import Page
from app.schemas.tag import TagCreate, TagRead, TagUpdate
from app.services.tag_cache import TagListCache, TagListCacheDep


class TagService:
    def __init__(self, session: SessionDep, cache: TagListCache | None = None) -> None:
        self._session = session
        self._tags = TagRepository(session)
        self._cache = cache

    async def get(self, tag_id: int) -> Tag:
        tag = await self._tags.get(tag_id)
        if tag is None:
            raise NotFoundError(f"Tag {tag_id} does not exist.", problem_type="tag-not-found")
        return tag

    async def list(self, *, page: int, size: int) -> Page[TagRead]:
        """One page, from the cache when there is one and it can answer."""
        if self._cache is None:
            return await self._load_page(page, size)
        return await self._cache.get_or_load(page, size, lambda: self._load_page(page, size))

    async def _load_page(self, page: int, size: int) -> Page[TagRead]:
        items = await self._tags.list(offset=(page - 1) * size, limit=size)
        return Page.of(
            [TagRead.model_validate(item) for item in items],
            total=await self._tags.count(),
            page=page,
            size=size,
        )

    async def _commit(self) -> None:
        """Commit, then orphan the cached pages — in that order, never the reverse."""
        await self._session.commit()
        if self._cache is not None:
            await self._cache.invalidate()

    async def create(self, payload: TagCreate) -> Tag:
        await self._reject_duplicate_name(payload.name)

        tag = await self._tags.add(Tag(**payload.model_dump()))
        await self._commit()
        return tag

    async def update(self, tag_id: int, payload: TagUpdate) -> Tag:
        tag = await self.get(tag_id)
        changes = payload.model_dump(exclude_unset=True)

        if "name" in changes:
            await self._reject_duplicate_name(changes["name"], exclude_id=tag_id)

        for field, value in changes.items():
            setattr(tag, field, value)

        await self._commit()
        return tag

    async def delete(self, tag_id: int) -> None:
        tag = await self.get(tag_id)
        await self._tags.delete(tag)
        await self._commit()

    async def _reject_duplicate_name(self, name: str, *, exclude_id: int | None = None) -> None:
        """See `ProjectService._reject_duplicate_name` on the race."""
        if await self._tags.name_exists(name, exclude_id=exclude_id):
            raise ConflictError(
                f"A tag named {name!r} already exists.", problem_type="duplicate-tag-name"
            )


async def get_tag_service(session: SessionDep, cache: TagListCacheDep) -> TagService:
    """Build the service on the event loop.

    Using the class itself as the dependency works, but FastAPI classifies a
    class as a synchronous callable and runs it in the thread pool — a hop, and
    one of AnyIO's shared thread tokens, on every request, to assign two
    attributes. An async factory stays on the loop.
    """
    return TagService(session, cache)


TagServiceDep = Annotated[TagService, Depends(get_tag_service)]
