"""Business rules and transaction boundaries for registering and logging in."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionDep
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.user import Token, UserRegister, normalize_username


class AuthService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def register(self, data: UserRegister) -> User:
        """Create a user, or 409 if the username is taken.

        `data.username` is already normalised by `UserRegister`'s own
        validator. The existence check below is what gives an ordinary
        duplicate a specific `username-taken` problem type instead of the
        generic 409 the database's unique index would produce on its own;
        the `except IntegrityError` below is what still catches it when two
        requests for the same username interleave between that check and this
        commit — the index is the real guard, this only keeps the message.
        """
        if await self._users.get_by_username(data.username) is not None:
            raise ConflictError(
                f"Username {data.username!r} is already taken.",
                problem_type="username-taken",
            )

        user = User(
            username=data.username,
            full_name=data.full_name,
            hashed_password=await hash_password(data.password),
        )
        try:
            await self._users.add(user)
            await self._session.commit()
        except IntegrityError as exc:
            raise ConflictError(
                f"Username {data.username!r} is already taken.",
                problem_type="username-taken",
            ) from exc
        return user

    async def login(self, username: str, password: str) -> Token:
        user = await self._users.get_by_username(normalize_username(username))
        # Decision 10: no dummy-hash timing equalisation. Usernames are
        # already public here — `GET /users/{username}/profile` answers
        # 404/200 and `register` answers 409 on the same username — so
        # treating an unknown user differently from a wrong password would
        # hide nothing a constant-time check could protect. One message,
        # whichever branch fails.
        if user is None or not await verify_password(password, user.hashed_password):
            raise UnauthorizedError("Incorrect username or password.")

        return Token(access_token=create_access_token(user.id))


async def get_auth_service(session: SessionDep) -> AuthService:
    """Built on the event loop — see `get_project_service` for why."""
    return AuthService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
