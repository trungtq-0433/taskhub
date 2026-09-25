"""The `tag` table."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import TAG_COLOR_LENGTH, TAG_NAME_MAX_LENGTH
from app.core.database import Base
from app.models.mixins import TimestampMixin


class Tag(Base, TimestampMixin):
    """A label a task can wear.

    Declares no relationship of its own. The many-to-many edge lives on
    `Task.tags`, through the `task_tag` association table, and there is no
    `Tag.tasks` counterpart on purpose: nothing reads the reverse direction,
    so it would be an unused attribute — and one that raises MissingGreenlet
    the first time something touches it outside an eager load.

    Deleting a tag therefore unlinks rather than being refused: the
    association rows carry `ON DELETE CASCADE`, so the database removes them
    and `DELETE /tags/{tag_id}` keeps answering 204.

    Still no relationship to `Project`. Tags hang off tasks, and a task
    belongs to a project, so the path already exists without a second one.
    """

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(TAG_NAME_MAX_LENGTH), unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(TAG_COLOR_LENGTH), default=None)

    def __repr__(self) -> str:
        return f"Tag(id={self.id!r}, name={self.name!r})"
