"""The user profile — a response that spans users and tasks.

A module of its own because of where it sits in the import graph. It needs
`UserRead` from the user schemas and `TaskCounts` from the task schemas, and the
task schemas already import from the user schemas (`TaskRead.assignee` is a
`UserSummary`). Placed in either of those two files, it would close a cycle —
Python executes imports top to bottom, so whichever module loads first stops
at its import line before the other one's classes exist. Here, above both, the
graph runs one way: `profile -> task -> user`.

Any future response that composes several resources belongs up here too.
"""

from app.schemas.base import BaseSchema
from app.schemas.task import TaskCounts
from app.schemas.user import UserRead


class UserProfile(BaseSchema):
    """Counts, not collections.

    Nothing here is a list, so the payload has a fixed size and needs no
    ceiling — which is the whole reason it was shaped this way.
    """

    user: UserRead
    project_count: int
    task_counts: TaskCounts
