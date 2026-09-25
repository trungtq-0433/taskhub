"""User DTOs — credentials in, profile out.

`UserRegister` and `UserUpdate` are the only two shapes in this module that
accept identity data from a client; everything else here only ever describes
a user that already exists. `normalize_username` lives here rather than in
`app.services.user` because both directions need the same rule:
`UserRegister` runs it inside its own validator (decision 13 in the auth
plan) and `UserService`/`AuthService` run it again on every lookup. Putting
it in this module — which no service is imported back into — is what keeps
that shared use from becoming an import cycle with `app.services.user`,
which already imports `UserRead` et al. from here.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.constants import (
    FULL_NAME_MAX_LENGTH,
    PASSWORD_MAX_BYTES,
    PASSWORD_MIN_LENGTH,
    USERNAME_MAX_LENGTH,
)
from app.schemas.base import BaseSchema


def normalize_username(value: str) -> str:
    """The one canonical form of a username: trimmed, then lowercase.

    Usernames are stored lowercase so a lookup can be a plain equality
    against the indexed column rather than `lower(username) = :name`, which
    no ordinary index serves. `UserRegister` normalises with this before
    checking the charset below, and every lookup normalises with it again
    before comparing — the same rule, write side and read side, stated once.
    """
    return value.strip().lower()


# Built from `USERNAME_MAX_LENGTH` rather than a literal 50: the schema and
# the `VARCHAR(50)` column already have to agree, per
# tests/test_schema_matches_columns.py, so the pattern is derived from the
# same constant instead of restating its value.
_USERNAME_PATTERN = re.compile(rf"^[a-z0-9_.-]{{3,{USERNAME_MAX_LENGTH}}}$")


class UserRegister(BaseSchema):
    """`POST /users/register` body. No email, no confirm-password field."""

    # The bounds here exist so tests/test_schema_matches_columns.py has a
    # MinLen/MaxLen annotation to check against the column width. The real
    # contract — charset, and length measured *after* normalising — is
    # enforced by the validator below, which runs on the already-bounded
    # value.
    username: str = Field(min_length=1, max_length=USERNAME_MAX_LENGTH)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)
    full_name: str | None = Field(default=None, max_length=FULL_NAME_MAX_LENGTH)

    @field_validator("username", mode="after")
    @classmethod
    def _normalize_and_check_charset(cls, value: str) -> str:
        normalized = normalize_username(value)
        if not _USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Username must be 3-50 characters of lowercase letters, digits, '_', '.', or '-'."
            )
        return normalized

    @field_validator("password", mode="after")
    @classmethod
    def _check_password_byte_length(cls, value: str) -> str:
        """bcrypt's own ceiling — see `PASSWORD_MAX_BYTES` in `app.constants`."""
        byte_length = len(value.encode("utf-8"))
        if byte_length > PASSWORD_MAX_BYTES:
            raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes.")
        return value


class UserUpdate(BaseSchema):
    """`PUT /users/me` body — `full_name` only (decision 5 in the auth plan).

    No default: an omitted key is 422 (PUT replaces, it does not patch), and
    an explicit `null` clears the column, which is a legitimate request
    because `full_name` is nullable.
    """

    full_name: str | None = Field(max_length=FULL_NAME_MAX_LENGTH)


class Token(BaseSchema):
    """`POST /users/login` response — the OAuth2 password-flow shape."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — the OAuth2 scheme name, not a secret


class UserSummary(BaseSchema):
    """A user as it appears nested inside another resource.

    No timestamps: when a user is shown as the assignee of a task, when that
    user row was created says nothing about the task.
    """

    id: int
    username: str
    full_name: str | None


class UserRead(UserSummary):
    created_at: datetime
    updated_at: datetime
