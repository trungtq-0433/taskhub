"""The `project` table."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import PROJECT_NAME_MAX_LENGTH, PROJECT_STATUS_MAX_LENGTH, ProjectStatus
from app.core.database import Base
from app.models.mixins import TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # VARCHAR, not a Postgres ENUM — see ProjectStatus for why. The allowed
    # values live there so this column and the schemas cannot drift apart.
    status: Mapped[str] = mapped_column(
        String(PROJECT_STATUS_MAX_LENGTH),
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE,
    )

    def __repr__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r})"
