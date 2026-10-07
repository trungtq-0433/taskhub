"""The `user` table."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import true

from app.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    HASHED_PASSWORD_LENGTH,
    USER_ROLE_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
    UserRole,
)
from app.core.database import Base
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """A person who can log in, and a task can be assigned to.

    `hashed_password` is NOT NULL with no default: every row is a row someone
    can authenticate as. It holds a bcrypt hash, never the plaintext, and is
    produced and checked only through `app.core.security` — nothing here
    enforces that, so no other module should assign to this column directly.

    `role` and `is_active` are changed only through SQL — there is no
    endpoint for either. Both are read from this row on every request, never
    from a JWT claim, so a demotion or deactivation takes effect on the very
    next request rather than only after the old token expires. An account can
    be disabled and, later, re-enabled the same way: an operator with `psql`,
    not an API call.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lowercase, so the unique index and the URL lookup agree without a
    # functional index. Normalising is the service's job; the column holds the
    # result and nothing here can enforce it.
    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(FULL_NAME_MAX_LENGTH), default=None)
    # Optional. Stored lowercase by the schema (`Email`), so the plain unique
    # index is case-safe like `username`'s; NULLs never collide, so any number
    # of users may have no address. Only `UserPrivate` ever returns it.
    email: Mapped[str | None] = mapped_column(
        String(EMAIL_MAX_LENGTH), unique=True, index=True, default=None
    )
    hashed_password: Mapped[str] = mapped_column(String(HASHED_PASSWORD_LENGTH))
    # VARCHAR, not a Postgres ENUM — see UserRole for why.
    role: Mapped[str] = mapped_column(
        String(USER_ROLE_MAX_LENGTH),
        default=UserRole.USER,
        server_default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, username={self.username!r})"
