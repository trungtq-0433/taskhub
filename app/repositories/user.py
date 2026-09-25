"""Queries against the `user` table. No business rules live here."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User


class UserRepository:
    """Read-side only.

    There is no `add` and no `username_exists`: nothing in the application
    writes a user row — the API has no endpoint that creates one — and a
    repository method with no caller is dead weight. Test fixtures build users
    with `session.add(User(...))` directly.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        """Plain equality — usernames are stored lowercase.

        Normalising on the way in is what lets this be an ordinary indexed
        comparison instead of `lower(username) = :name`, which would need a
        matching functional index to avoid a sequential scan.
        """
        result = await self._session.scalars(select(User).where(User.username == username))
        return result.one_or_none()

    async def count_projects(self, user_id: int) -> int:
        """Projects this user owns.

        A project with a NULL owner counts toward nobody. That is the correct
        reading of an ownerless project, not a row waiting to be repaired.
        """
        total = await self._session.scalar(
            select(func.count()).select_from(Project).where(Project.owner_id == user_id)
        )
        return total or 0
