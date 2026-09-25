"""User endpoints. Routing and shaping only — no business logic."""

from fastapi import APIRouter

from app.api.params import not_found
from app.schemas.profile import UserProfile
from app.services.user import UserServiceDep

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{username}/profile", summary="Fetch a user's profile", responses=not_found("user"))
async def get_profile(username: str, service: UserServiceDep) -> UserProfile:
    """Counts, not collections: projects owned and tasks assigned by status.

    The lookup is case-insensitive because usernames are stored lowercase and
    the path segment is lowercased before the comparison.

    Nothing in this API creates a user, so on a fresh database every username
    answers 404 until a row is inserted by hand.
    """
    return await service.get_profile(username)
