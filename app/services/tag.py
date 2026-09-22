"""Business rules and transaction boundaries for tags."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Tag
from app.repositories.tag import TagRepository
from app.schemas.tag import TagCreate, TagUpdate


class TagService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._tags = TagRepository(session)

    async def get(self, tag_id: int) -> Tag:
        tag = await self._tags.get(tag_id)
        if tag is None:
            raise NotFoundError(f"Tag {tag_id} does not exist.", problem_type="tag-not-found")
        return tag

    async def list(self, *, page: int, size: int) -> tuple[list[Tag], int]:
        items = await self._tags.list(offset=(page - 1) * size, limit=size)
        return list(items), await self._tags.count()

    async def create(self, payload: TagCreate) -> Tag:
        await self._reject_duplicate_name(payload.name)

        tag = await self._tags.add(Tag(**payload.model_dump()))
        await self._session.commit()
        return tag

    async def update(self, tag_id: int, payload: TagUpdate) -> Tag:
        tag = await self.get(tag_id)
        changes = payload.model_dump(exclude_unset=True)

        if "name" in changes:
            await self._reject_duplicate_name(changes["name"], exclude_id=tag_id)

        for field, value in changes.items():
            setattr(tag, field, value)

        await self._session.commit()
        return tag

    async def delete(self, tag_id: int) -> None:
        tag = await self.get(tag_id)
        await self._tags.delete(tag)
        await self._session.commit()

    async def _reject_duplicate_name(self, name: str, *, exclude_id: int | None = None) -> None:
        """See `ProjectService._reject_duplicate_name` on the race."""
        if await self._tags.name_exists(name, exclude_id=exclude_id):
            raise ConflictError(
                f"A tag named {name!r} already exists.", problem_type="duplicate-tag-name"
            )


TagServiceDep = Annotated[TagService, Depends()]
