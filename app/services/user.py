"""Business rules for reading, and for editing, a user.

Registration and login are `AuthService`'s job (`app.services.auth`) — this
class covers everything a user does once already authenticated: reading a
profile, and `update_me`.
"""

import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionDep
from app.core.exceptions import ConflictError, NotFoundError
from app.models import User
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.schemas.profile import UserProfile
from app.schemas.task import TaskCounts
from app.schemas.user import UserRead, UserUpdate, normalize_username

logger = logging.getLogger(__name__)


def email_taken(email: str) -> ConflictError:
    """The one 409 for an address another user holds — register and `PUT /users/me` share it."""
    return ConflictError(f"Email {email!r} is already registered.", problem_type="email-taken")


class UserService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._tasks = TaskRepository(session)

    async def update_me(self, user: User, data: UserUpdate) -> User:
        """Set `full_name`, apply `email` if the client sent the key, and commit.

        See `UserUpdate` for why `email` alone may be absent: `model_fields_set`
        is what separates "kept" from an explicit `null` ("cleared"). The caller's
        own current address is not a conflict, so it skips the pre-check; what
        remains of `IntegrityError` is a genuine race on the unique index — the
        index is the real guard, the pre-check only keeps the message, as in
        `AuthService.register`. Username is immutable, so `email-taken` is the
        only unique violation this route can see.
        """
        user.full_name = data.full_name
        if "email" in data.model_fields_set:
            if (
                data.email is not None
                and data.email != user.email
                and await self._users.get_by_email(data.email) is not None
            ):
                raise email_taken(data.email)
            user.email = data.email
        try:
            await self._session.commit()
        except IntegrityError as exc:
            if data.email is not None and "ix_user_email" in str(exc.orig):
                raise email_taken(data.email) from exc
            raise
        await self._session.refresh(user)
        return user

    async def get_profile(self, username: str) -> UserProfile:
        """Counts, gathered in two queries.

        A username nobody has registered through `POST /users/register`
        answers 404.
        """
        user = await self._users.get_by_username(normalize_username(username))
        if user is None:
            raise NotFoundError(f"No user named {username!r}.", problem_type="user-not-found")

        counts = await self._tasks.count_by_status_for_assignee(user.id)
        self._warn_about_statuses_the_response_cannot_carry(user.username, counts)

        return UserProfile(
            user=UserRead.model_validate(user),
            project_count=await self._users.count_projects(user.id),
            task_counts=TaskCounts.model_validate(counts),
        )

    @staticmethod
    def _warn_about_statuses_the_response_cannot_carry(
        username: str, counts: dict[str, int]
    ) -> None:
        """Say something when the DTO is about to swallow a count.

        `TaskCounts` carries one field per member of `TaskStatus` and inherits
        `extra="ignore"`, so a status the enum no longer knows is dropped on
        the way out — the tasks are still assigned, they just stop being
        counted, and the response has no `total` a client could notice the gap
        with. That is an expected state rather than a corrupt one: the column
        is VARCHAR so the status set can change without a migration, which
        leaves old rows holding a value nothing recognises.

        Logged rather than raised. One stale row should not take the endpoint
        down, and the count is the thing that is wrong, not the request.
        """
        lost = {
            status: count
            for status, count in counts.items()
            if status not in TaskCounts.model_fields
        }
        if lost:
            logger.warning(
                "Profile for %r drops %d task(s) whose status the response cannot carry: %s. "
                "Every status outside TaskStatus is invisible to the client.",
                username,
                sum(lost.values()),
                sorted(lost),
            )


async def get_user_service(session: SessionDep) -> UserService:
    """Built on the event loop — see `get_project_service` for why."""
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
