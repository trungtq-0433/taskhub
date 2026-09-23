"""Project DTOs — what crosses the wire, in three genuinely different shapes."""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.constants import (
    NAME_MIN_LENGTH,
    PROJECT_DESCRIPTION_MAX_LENGTH,
    PROJECT_NAME_MAX_LENGTH,
    ProjectStatus,
)
from app.schemas.base import BaseSchema, NotNull


class ProjectCreate(BaseSchema):
    name: str = Field(min_length=NAME_MIN_LENGTH, max_length=PROJECT_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=PROJECT_DESCRIPTION_MAX_LENGTH)
    status: ProjectStatus = ProjectStatus.ACTIVE


class ProjectUpdate(BaseSchema):
    """Every field optional — that is what makes PATCH partial.

    Read this with `model_dump(exclude_unset=True)`. A plain `model_dump()`
    fills the omitted fields with `None` and nulls those columns, which is the
    difference between "leave the description alone" and "delete it".
    """

    # name and status map to NOT NULL columns, so null is refused there.
    # description is nullable, so clearing it with null is legitimate.
    name: Annotated[str | None, NotNull] = Field(
        default=None, min_length=NAME_MIN_LENGTH, max_length=PROJECT_NAME_MAX_LENGTH
    )
    description: str | None = Field(default=None, max_length=PROJECT_DESCRIPTION_MAX_LENGTH)
    status: Annotated[ProjectStatus | None, NotNull] = None


class ProjectRead(BaseSchema):
    id: int
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
