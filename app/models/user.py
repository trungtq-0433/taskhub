"""The `user` table."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import FULL_NAME_MAX_LENGTH, HASHED_PASSWORD_LENGTH, USERNAME_MAX_LENGTH
from app.core.database import Base
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """A person who can log in, and a task can be assigned to.

    `hashed_password` is NOT NULL with no default: every row is a row someone
    can authenticate as. It holds a bcrypt hash, never the plaintext, and is
    produced and checked only through `app.core.security` — nothing here
    enforces that, so no other module should assign to this column directly.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lowercase, so the unique index and the URL lookup agree without a
    # functional index. Normalising is the service's job; the column holds the
    # result and nothing here can enforce it.
    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(FULL_NAME_MAX_LENGTH), default=None)
    hashed_password: Mapped[str] = mapped_column(String(HASHED_PASSWORD_LENGTH))

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, username={self.username!r})"
