"""`can_manage_project` in isolation — pure, no HTTP, no database.

Every object here is unsaved. That is the point: the rule has to be correct
before a session or a request ever exists, or the guarded routes that call it
would be the first place it gets exercised.
"""

from app.api.permissions import can_manage_project
from app.constants import UserRole
from app.models import Project, User
from tests.factories import make_user


def _project(*, owner_id: int | None) -> Project:
    project = Project(name="Unsaved")
    project.owner_id = owner_id
    return project


def _user(username: str, *, user_id: int | None, role: UserRole = UserRole.USER) -> User:
    user = make_user(username, role=role)
    if user_id is not None:
        user.id = user_id
    return user


def test_owner_can_manage_their_own_project() -> None:
    owner = _user("owning-user", user_id=1)
    assert can_manage_project(owner, _project(owner_id=1)) is True


def test_another_user_cannot_manage_it() -> None:
    other = _user("other-user", user_id=2)
    assert can_manage_project(other, _project(owner_id=1)) is False


def test_admin_can_manage_another_users_project() -> None:
    admin = _user("admin-user", user_id=99, role=UserRole.ADMIN)
    assert can_manage_project(admin, _project(owner_id=1)) is True


def test_admin_can_manage_an_ownerless_project() -> None:
    admin = _user("admin-user-2", user_id=99, role=UserRole.ADMIN)
    assert can_manage_project(admin, _project(owner_id=None)) is True


def test_ordinary_user_cannot_manage_an_ownerless_project() -> None:
    """The explicit `is not None` check: without it, an unsaved user's `id`
    of `None` would equal an ownerless project's `owner_id` of `None`, and a
    user who was never flushed would "own" every ownerless project."""
    user = _user("member-user", user_id=None)
    assert can_manage_project(user, _project(owner_id=None)) is False
