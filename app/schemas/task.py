"""Task DTOs — the only place in this API where data nests."""

from datetime import datetime

from pydantic import Field

from app.constants import (
    NAME_MIN_LENGTH,
    TASK_DESCRIPTION_MAX_LENGTH,
    TASK_MAX_TAGS,
    TASK_TITLE_MAX_LENGTH,
    TaskStatus,
)
from app.schemas.base import BaseSchema
from app.schemas.tag import TagRead
from app.schemas.user import UserSummary


class TaskCreate(BaseSchema):
    """`assignee_id` and `tag_ids` are checked for existence by the service.

    Both name rows the client cannot see from here, so a wrong id is a 422
    naming the id rather than an integrity error the client cannot read.
    """

    title: str = Field(min_length=NAME_MIN_LENGTH, max_length=TASK_TITLE_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=TASK_DESCRIPTION_MAX_LENGTH)
    status: TaskStatus = TaskStatus.TODO
    assignee_id: int | None = None
    # Capped: this list becomes an `IN` clause, and an unbounded one is an
    # unbounded query built from client input.
    tag_ids: list[int] = Field(default_factory=list, max_length=TASK_MAX_TAGS)


class TaskRead(BaseSchema):
    """Nested on both edges: many-to-one on `assignee`, many-to-many on `tags`.

    Both are populated by the repository's eager options. Reading either one
    without them raises `MissingGreenlet` under `AsyncSession` — a 500, not a
    slow response.
    """

    id: int
    title: str
    description: str | None
    status: TaskStatus
    project_id: int
    assignee: UserSummary | None
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime


# Here rather than with the user schemas because its fields are the task
# status set: one per member of `TaskStatus`, so adding a status means changing
# this class too — `test_task_counts_has_one_field_per_task_status` fails if
# that is forgotten. A comment rather than part of the docstring on purpose:
# Pydantic publishes the docstring as this schema's description in OpenAPI,
# and file layout is nothing a client needs to read.
class TaskCounts(BaseSchema):
    """Tasks assigned to a user, split by status.

    No `total` field. It is the sum of the three, and a stored sum is a second
    truth that can disagree with the first.
    """

    todo: int
    doing: int
    done: int
