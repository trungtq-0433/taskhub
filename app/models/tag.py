"""The `tag` table."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Tag(Base, TimestampMixin):
    """A standalone label.

    No relationship to `Project` on purpose: tags conventionally hang off
    `Task`, which does not exist yet, and a join table built on a guess is
    harder to remove than to add.
    """

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(7), default=None)

    def __repr__(self) -> str:
        return f"Tag(id={self.id!r}, name={self.name!r})"
