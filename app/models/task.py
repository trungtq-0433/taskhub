"""The `task` table."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import TASK_STATUS_MAX_LENGTH, TASK_TITLE_MAX_LENGTH, TaskStatus
from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.task_tag import task_tag

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.tag import Tag
    from app.models.user import User


class Task(Base, TimestampMixin):
    """A unit of work inside a project, optionally assigned and tagged."""

    __tablename__ = "task"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(TASK_TITLE_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # VARCHAR, not a Postgres ENUM — see TaskStatus for why.
    status: Mapped[str] = mapped_column(
        String(TASK_STATUS_MAX_LENGTH),
        default=TaskStatus.TODO,
        server_default=TaskStatus.TODO,
    )

    # RESTRICT is the real guard behind the service's pre-check: deleting a
    # project that still has tasks is refused by the database, so a service
    # that forgets to check cannot destroy anything.
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="RESTRICT"), index=True
    )
    # Nullable, and SET NULL on delete: an unassigned task is an ordinary
    # state, and removing a user must not take their tasks with them.
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship()
    # No `Tag.tasks` counterpart: nothing reads the reverse direction, and the
    # database-level cascade already handles what happens when a tag goes.
    tags: Mapped[list["Tag"]] = relationship(secondary=task_tag)

    def __repr__(self) -> str:
        return f"Task(id={self.id!r}, title={self.title!r})"
