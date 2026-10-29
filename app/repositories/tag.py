"""Queries against the `tag` table. No business rules live here."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tag_id: int) -> Tag | None:
        return await self._session.get(Tag, tag_id)

    async def list(self, *, offset: int, limit: int) -> Sequence[Tag]:
        statement = select(Tag).order_by(Tag.name).offset(offset).limit(limit)
        return (await self._session.scalars(statement)).all()

    async def count(self) -> int:
        total = await self._session.scalar(select(func.count()).select_from(Tag))
        return total or 0

    # `Sequence[int]`, not `list[int]`: inside this class body the name `list`
    # resolves to the method above, and mypy rejects a method used as a type.
    async def list_by_ids(self, tag_ids: Sequence[int]) -> Sequence[Tag]:
        """The tags named by a client, in one statement rather than a loop.

        Returning fewer rows than ids given is not an error here: it is the
        input the service turns into a 422 naming the ids that do not exist.
        An empty input returns early rather than emitting `IN ()`.
        """
        if not tag_ids:
            return []
        return (await self._session.scalars(select(Tag).where(Tag.id.in_(tag_ids)))).all()

    async def add(self, tag: Tag) -> Tag:
        """Flush, never commit — see `ProjectRepository.add`."""
        self._session.add(tag)
        await self._session.flush()
        return tag

    async def delete(self, tag: Tag) -> None:
        await self._session.delete(tag)
        await self._session.flush()

    async def name_exists(self, name: str, *, exclude_id: int | None = None) -> bool:
        statement = select(Tag.id).where(Tag.name == name)
        if exclude_id is not None:
            statement = statement.where(Tag.id != exclude_id)
        return await self._session.scalar(statement.limit(1)) is not None
