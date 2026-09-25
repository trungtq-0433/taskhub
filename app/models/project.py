"""The `project` table."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import PROJECT_NAME_MAX_LENGTH, PROJECT_STATUS_MAX_LENGTH, ProjectStatus
from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.task import Task


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
    # Nullable: a project with no owner is a valid, expected state, not a data
    # defect. Nothing in the API sets this column — POST /projects does not
    # accept it — so it is reached only by fixtures and hand-written SQL while
    # still backing the profile's project count. SET NULL on delete follows:
    # removing a user leaves their projects behind rather than being refused.
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True
    )

    # passive_deletes="all" is load-bearing. Without it the ORM loads the
    # children on session.delete(project) and sets task.project_id = NULL — a
    # NOT NULL column — so the delete fails as a generic 409 instead of the
    # specific one the service raises. Under AsyncSession it is worse: that
    # implicit load raises MissingGreenlet before the FK is reached. With it,
    # the ORM emits the DELETE and lets the database's RESTRICT answer.
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", passive_deletes="all")

    def __repr__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r})"
