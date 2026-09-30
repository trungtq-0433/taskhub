"""`get_current_user` and `get_current_active_user` — the one gate `/users/me`
sits behind, and the one layer past it that a disabled account cannot clear."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.database import SessionDep
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.models import User
from app.repositories.user import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/users/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    """Resolve the bearer token to a `User`, or refuse the request.

    A request with no `Authorization` header never reaches this body:
    `OAuth2PasswordBearer` raises its own 401 first, with `WWW-Authenticate`
    intact now that `http_exception_handler` forwards `exc.headers`. From
    here on, a token that fails to decode and a token that decodes but names
    a user no longer in the table (deleted, per decision 12) get the
    identical 401 a forged token would.
    """
    user_id = decode_access_token(token)
    if user_id is None:
        raise UnauthorizedError("Could not validate credentials.")

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise UnauthorizedError("Could not validate credentials.")

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_active_user(user: CurrentUserDep) -> User:
    """One layer past `get_current_user`: a real, undeleted account that has
    not been switched off.

    Kept separate rather than folded into `get_current_user` so a deleted
    user and a disabled one stay distinguishable at the dependency level: the
    first is 401 (no such credential), the second 403 (a credential that is
    valid but refused). `is_active` is read from the row loaded above, never
    from the token, so a deactivation takes effect on the account's very next
    request rather than only after the old token expires.
    """
    if not user.is_active:
        raise ForbiddenError("This account is disabled.", problem_type="inactive-user")
    return user


ActiveUserDep = Annotated[User, Depends(get_current_active_user)]
