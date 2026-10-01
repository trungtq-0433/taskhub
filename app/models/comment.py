"""The `Comment` model: a note left on a task.

`author_id` is `SET NULL`, not `CASCADE`: removing a user must not erase what
was said in a thread, so the comment stays readable with no author — the same
choice as `Task.assignee`. `task_id` is `CASCADE`: a comment has no meaning
without its task.

No `Task.comments` or `User.comments` counterpart. Nothing reads the reverse
direction, and a collection on `Task` would need `passive_deletes` to avoid an
implicit async load on delete; the database's CASCADE already removes the rows.
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Comment(TimestampMixin, Base):
    __tablename__ = "comment"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True
    )
    # TEXT, so the length limit is enforced by the API only.
    content: Mapped[str] = mapped_column(Text)

    author: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"Comment(id={self.id!r}, task_id={self.task_id!r})"
