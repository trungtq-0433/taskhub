"""The `task_tag` association table.

A Core `Table` rather than a declarative class: the association carries no
columns of its own, so there is nothing for a class to hold. SQLAlchemy reads
it straight through `secondary=` on `Task.tags`.

Registered in `app/models/__init__.py` like every model, and for the same
reason — a table missing from `Base.metadata` is a table Alembic believes was
deleted, and `--autogenerate` then emits `DROP TABLE` without erroring.
"""

from sqlalchemy import Column, ForeignKey, Index, Table

from app.core.database import Base

task_tag = Table(
    "task_tag",
    Base.metadata,
    # CASCADE on both sides: the row is a link, not data. Deleting a task drops
    # its links, and `DELETE /tags/{id}` — already merged — unlinks rather than
    # being refused.
    Column("task_id", ForeignKey("task.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
    # The composite primary key indexes (task_id, tag_id) and so covers lookups
    # that lead with task_id. Nothing covers tag_id alone, which is the column
    # Postgres scans when a tag is deleted — without this index that delete
    # sequentially scans the whole association table.
    Index("ix_task_tag_tag_id", "tag_id"),
)
