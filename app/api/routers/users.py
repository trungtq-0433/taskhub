"""User endpoints. Routing and shaping only — no business logic."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.auth import CurrentUserDep
from app.api.params import UNAUTHORIZED, ErrorResponses, not_found
from app.core.handlers import PROBLEM_CONTENT
from app.schemas.profile import UserProfile
from app.schemas.user import Token, UserPrivate, UserRegister, UserUpdate
from app.services.auth import AuthServiceDep
from app.services.user import UserServiceDep

router = APIRouter(prefix="/users", tags=["users"])

USERNAME_OR_EMAIL_TAKEN: ErrorResponses = {
    409: {"content": PROBLEM_CONTENT, "description": "Username or email already taken"}
}
EMAIL_TAKEN: ErrorResponses = {
    **UNAUTHORIZED,
    409: {"content": PROBLEM_CONTENT, "description": "Email already taken"},
}


@router.post(
    "/register",
    summary="Register a new user",
    status_code=status.HTTP_201_CREATED,
    responses=USERNAME_OR_EMAIL_TAKEN,
)
async def register(payload: UserRegister, service: AuthServiceDep) -> UserPrivate:
    """`username` and, if given, `email` must be unique; a clash answers 409, not 422."""
    return UserPrivate.model_validate(await service.register(payload))


@router.post(
    "/login",
    summary="Log in and receive an access token",
    responses=UNAUTHORIZED,
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], service: AuthServiceDep
) -> Token:
    """Standard OAuth2 password flow: form-encoded body, not JSON.

    Unknown username and wrong password answer the same 401 — see
    `AuthService.login`.
    """
    return await service.login(form.username, form.password)


@router.get("/me", summary="Fetch the current user", responses=UNAUTHORIZED)
async def get_me(user: CurrentUserDep) -> UserPrivate:
    return UserPrivate.model_validate(user)


@router.put("/me", summary="Update the current user", responses=EMAIL_TAKEN)
async def update_me(
    payload: UserUpdate, user: CurrentUserDep, service: UserServiceDep
) -> UserPrivate:
    """`full_name` and, optionally, `email` — username stays immutable. See `UserUpdate`."""
    return UserPrivate.model_validate(await service.update_me(user, payload))


@router.get("/{username}/profile", summary="Fetch a user's profile", responses=not_found("user"))
async def get_profile(username: str, service: UserServiceDep) -> UserProfile:
    """Counts, not collections: projects owned and tasks assigned by status.

    The lookup is case-insensitive because usernames are stored lowercase and
    the path segment is lowercased before the comparison.
    """
    return await service.get_profile(username)
