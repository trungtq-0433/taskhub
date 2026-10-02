"""Queries against the `comment` table. No business rules live here."""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, comment_id: int) -> Comment | None:
        return await self._session.get(Comment, comment_id)

    async def add(self, comment: Comment) -> Comment:
        """Flush, never commit — see `ProjectRepository.add`."""
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def delete(self, *, comment_id: int, task_id: int) -> bool:
        """Whether this statement removed the row.

        Conditional on both ids and judged by `RETURNING`, so two deletes that
        both passed an earlier read cannot both succeed: the loser gets no row
        back. `ORM session.delete()` would answer success either way.
        """
        deleted = await self._session.scalar(
            delete(Comment)
            .where(Comment.id == comment_id, Comment.task_id == task_id)
            .returning(Comment.id)
        )
        return deleted is not None
