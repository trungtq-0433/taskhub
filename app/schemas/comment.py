"""Comment DTOs.

`CommentCreate` carries the content and nothing else: the author comes from the
token and the task from the path, so neither is a field a body could set. An
`author_id` or `task_id` sent anyway is dropped by `BaseSchema`'s
`extra="ignore"`, not rejected.
"""

from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints

from app.constants import COMMENT_CONTENT_MAX_LENGTH
from app.schemas.base import BaseSchema
from app.schemas.user import UserSummary

# pydantic-core strips first and measures after, so "   " is 422, not a blank comment.
CommentContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=COMMENT_CONTENT_MAX_LENGTH),
]


class CommentCreate(BaseSchema):
    content: CommentContent


class CommentRead(BaseSchema):
    """`author` is `None` once the author's account has been removed; the comment stays."""

    id: int
    task_id: int
    author: UserSummary | None
    content: str
    created_at: datetime
    updated_at: datetime
