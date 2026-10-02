"""`can_manage_project` and `can_modify_comment` in isolation — pure, no HTTP, no database.

Every object here is unsaved. That is the point: the rule has to be correct
before a session or a request ever exists, or the guarded routes that call it
would be the first place it gets exercised.
"""

from app.api.permissions import can_manage_project, can_modify_comment
from app.constants import UserRole
from app.models import Comment, Project, User
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


def _comment(*, author_id: int | None) -> Comment:
    return Comment(task_id=1, content="note", author_id=author_id)


def test_author_can_modify_their_own_comment() -> None:
    author = _user("comment-author", user_id=5)
    assert can_modify_comment(author, _comment(author_id=5), _project(owner_id=1)) is True


def test_admin_can_modify_anyones_comment() -> None:
    admin = _user("comment-admin", user_id=99, role=UserRole.ADMIN)
    assert can_modify_comment(admin, _comment(author_id=5), _project(owner_id=1)) is True


def test_the_projects_owner_can_modify_a_comment_on_its_task() -> None:
    owner = _user("comment-owner", user_id=1)
    assert can_modify_comment(owner, _comment(author_id=5), _project(owner_id=1)) is True


def test_another_user_cannot_modify_it() -> None:
    other = _user("comment-other", user_id=2)
    assert can_modify_comment(other, _comment(author_id=5), _project(owner_id=1)) is False


def test_an_unsaved_user_cannot_modify_a_comment_whose_author_was_deleted() -> None:
    """The `is not None` guard: `None == None` must not make an author."""
    user = _user("comment-unsaved", user_id=None)
    assert can_modify_comment(user, _comment(author_id=None), _project(owner_id=1)) is False


def test_an_ordinary_user_cannot_modify_an_authorless_comment_on_an_ownerless_project() -> None:
    user = _user("comment-ordinary", user_id=7)
    assert can_modify_comment(user, _comment(author_id=None), _project(owner_id=None)) is False
