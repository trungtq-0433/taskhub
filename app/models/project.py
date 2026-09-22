"""The `project` table."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # VARCHAR rather than a Postgres ENUM: native enums need their own
    # CREATE TYPE / DROP TYPE in migrations, which autogenerate does not handle
    # reliably. The Pydantic layer holds the allowed values, so clients get the
    # same guarantee without the migration ceremony.
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")

    def __repr__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r})"
