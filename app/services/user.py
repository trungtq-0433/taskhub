"""Business rules for reading a user. Nothing here writes one."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.exceptions import NotFoundError
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.schemas.user import TaskCounts, UserProfile, UserRead


def normalize_username(value: str) -> str:
    """The one canonical form of a username: lowercase.

    A named helper with a single caller today, on purpose. Usernames are stored
    lowercase so the lookup can be a plain equality against the indexed column
    rather than `lower(username) = :name`, which no ordinary index serves. That
    rule has two sides — the write that stores it and the read that looks it up
    — and the write side does not exist yet because nothing in the API creates
    a user. Inlining `.lower()` into the lookup would leave the rule stated
    nowhere, and the day a write path appears it would be restated by hand.
    """
    return value.strip().lower()


class UserService:
    def __init__(self, session: SessionDep) -> None:
        self._users = UserRepository(session)
        self._tasks = TaskRepository(session)

    async def get_profile(self, username: str) -> UserProfile:
        """Counts, gathered in two queries.

        On a fresh database this answers 404 for every username: no endpoint
        creates a user, so rows arrive only from a fixture or by hand. That is
        the accepted consequence of keeping this API to three endpoints, not a
        defect to be worked around here.
        """
        user = await self._users.get_by_username(normalize_username(username))
        if user is None:
            raise NotFoundError(f"No user named {username!r}.", problem_type="user-not-found")

        counts = await self._tasks.count_by_status_for_assignee(user.id)
        return UserProfile(
            user=UserRead.model_validate(user),
            project_count=await self._users.count_projects(user.id),
            task_counts=TaskCounts.model_validate(counts),
        )


async def get_user_service(session: SessionDep) -> UserService:
    """Built on the event loop — see `get_project_service` for why."""
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
