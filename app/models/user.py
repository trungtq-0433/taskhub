"""The `user` table."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import FULL_NAME_MAX_LENGTH, USERNAME_MAX_LENGTH
from app.core.database import Base
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """A person a project can belong to and a task can be assigned to.

    No password, no email, no auth of any kind — nothing in the API
    authenticates, so a credential stored here would only be a liability. The
    row exists to be pointed at.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lowercase, so the unique index and the URL lookup agree without a
    # functional index. Normalising is the service's job; the column holds the
    # result and nothing here can enforce it.
    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(FULL_NAME_MAX_LENGTH), default=None)

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, username={self.username!r})"
