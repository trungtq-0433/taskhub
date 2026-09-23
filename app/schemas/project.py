"""Project DTOs — what crosses the wire, in three genuinely different shapes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.base import BaseSchema, NotNull

ProjectStatus = Literal["active", "archived"]


class ProjectCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    status: ProjectStatus = "active"


class ProjectUpdate(BaseSchema):
    """Every field optional — that is what makes PATCH partial.

    Read this with `model_dump(exclude_unset=True)`. A plain `model_dump()`
    fills the omitted fields with `None` and nulls those columns, which is the
    difference between "leave the description alone" and "delete it".
    """

    # name and status map to NOT NULL columns, so null is refused there.
    # description is nullable, so clearing it with null is legitimate.
    name: Annotated[str | None, NotNull] = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    status: Annotated[ProjectStatus | None, NotNull] = None


class ProjectRead(BaseSchema):
    id: int
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
