"""Queries against the `user` table. No business rules live here."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User


class UserRepository:
    """Queries against `user`, plus the one write: `add`.

    There is no `update`: a `User` already loaded by `get`/`get_by_username`
    is updated by assigning to its attributes and letting the service commit
    — see `UserService.update_me`. A method that would do nothing but
    `session.add` a row already in the session is dead weight.
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

    async def add(self, user: User) -> User:
        """Flush and refresh so the caller reads back the id and timestamps.

        `TimestampMixin`'s `eager_defaults` already returns them via
        `RETURNING` on the flush; the explicit refresh matches how the rest of
        this application's writes behave and costs one extra round trip only
        on the one path (`AuthService.register`) that calls this.
        """
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def count_projects(self, user_id: int) -> int:
        """Projects this user owns.

        A project with a NULL owner counts toward nobody. That is the correct
        reading of an ownerless project, not a row waiting to be repaired.
        """
        total = await self._session.scalar(
            select(func.count()).select_from(Project).where(Project.owner_id == user_id)
        )
        return total or 0
