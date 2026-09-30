"""The `task_bookmark` association table.

A Core `Table` rather than a declarative class, like `task_tag.py`: the
association carries only `created_at` beyond its two key columns, and there is
no behavior for a class to add. SQLAlchemy needs no ORM relationship on either
side — the only two operations against this table are an insert (bookmark)
and an existence check (the pre-check for the 409), neither of which needs to
walk from `User` or `Task`.

Registered in `app/models/__init__.py` like every model, and for the same
reason — a table missing from `Base.metadata` is a table Alembic believes was
deleted, and `--autogenerate` then emits `DROP TABLE` without erroring.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Table, func

from app.core.database import Base

task_bookmark = Table(
    "task_bookmark",
    Base.metadata,
    # The composite primary key leads with user_id, not task_id: both queries
    # this table serves lead with a user — the pre-check ("has this user
    # already bookmarked this task?") and the cascade when a user is deleted.
    # CASCADE on both sides: the row is a link, not data, and has no meaning
    # once either side is gone.
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("task_id", ForeignKey("task.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # The composite primary key indexes (user_id, task_id) and so covers
    # lookups that lead with user_id. Nothing covers task_id alone, which is
    # the column Postgres scans when a task is deleted — without this index
    # that delete sequentially scans the whole association table.
    Index("ix_task_bookmark_task_id", "task_id"),
)
