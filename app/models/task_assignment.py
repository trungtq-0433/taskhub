"""The `task_assignment` table: insert-only history of who assigned what.

A Core `Table` with no ORM class and no read path — rows are written when an
assignment changes and nothing reads them back yet. `id` is the authoritative
order; `created_at` uses `clock_timestamp()` rather than `now()` because `now()`
is the transaction's start time, and a transaction that waited on the task row
lock started before the one it waited for, so ordering by it could invert the
chain.

`assigned_by_id` is `RESTRICT` and NOT NULL: it is the only record of who made
the change, so deleting that user must be refused rather than anonymize it.
`assignee_id` is `SET NULL`: removing a user never deletes someone
else's history row. `task_id` is `CASCADE`: history has no meaning without the
task. A Core `Column` is nullable by default, hence the explicit `nullable=False`.

Registered in `app/models/__init__.py` like every model — a table missing from
`Base.metadata` is a table Alembic believes was deleted, and `--autogenerate`
then emits `DROP TABLE` without erroring.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, func

from app.core.database import Base

task_assignment = Table(
    "task_assignment",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("task_id", ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("assignee_id", ForeignKey("user.id", ondelete="SET NULL"), index=True),
    Column(
        "assigned_by_id", ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    ),
)
