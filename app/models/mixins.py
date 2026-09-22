"""Column groups shared by every entity."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """`created_at` / `updated_at`, in the one combination that behaves.

    `timezone=True` compiles to `TIMESTAMPTZ` and makes SQLAlchemy return
    tz-aware datetimes; without it every comparison against `datetime.now(UTC)`
    raises. It is also spelled out explicitly rather than inferred from the
    annotation, because `compare_type=True` would otherwise flag a phantom type
    change against the real `timestamptz` column on every autogenerate.

    `server_default` puts the stamp on the row at the database, so a backfill or
    raw INSERT gets it too. `onupdate` is an ORM-side event with no DDL
    footprint — invisible to Alembic, and bypassed by raw SQL updates, which is
    acceptable while every write goes through the service layer.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
