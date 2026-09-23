"""User DTOs — read-side only.

Nothing in the API creates or edits a user, so there is no `UserCreate` and no
`UserUpdate`. A user row is written by a fixture or by hand; these shapes exist
to read one back.
"""

from datetime import datetime

from app.schemas.base import BaseSchema


class UserSummary(BaseSchema):
    """A user as it appears nested inside another resource.

    No timestamps: when a user is shown as the assignee of a task, when that
    user row was created says nothing about the task.
    """

    id: int
    username: str
    full_name: str | None


class UserRead(UserSummary):
    created_at: datetime
    updated_at: datetime


class TaskCounts(BaseSchema):
    """Tasks assigned to a user, split by status.

    No `total` field. It is the sum of the three, and a stored sum is a second
    truth that can disagree with the first.
    """

    todo: int
    doing: int
    done: int


class UserProfile(BaseSchema):
    """Counts, not collections.

    Nothing here is a list, so the payload has a fixed size and needs no
    ceiling — which is the whole reason it was shaped this way.
    """

    user: UserRead
    project_count: int
    task_counts: TaskCounts
