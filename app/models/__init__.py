"""Every model is imported here, and Alembic imports only this module.

This is load-bearing, not tidiness. `target_metadata` contains a table only if
its module has actually been executed, and a model Alembic cannot see is a
model it believes was deleted — `--autogenerate` then emits a migration that
DROPS the table, without erroring. Adding a model without adding it here is the
classic way to lose data on the next `upgrade head`.
"""

from app.models.project import Project
from app.models.tag import Tag
from app.models.task import Task
from app.models.task_tag import task_tag
from app.models.user import User

__all__ = ["Project", "Tag", "Task", "User", "task_tag"]
