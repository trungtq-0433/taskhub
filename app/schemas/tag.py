"""Tag DTOs."""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.schemas.base import BaseSchema, NotNull

# #RGB is not accepted: one canonical form means clients never have to
# normalise before comparing.
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class TagCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class TagUpdate(BaseSchema):
    """All optional — see the note on `ProjectUpdate`."""

    # name maps to a NOT NULL column; color is nullable.
    name: Annotated[str | None, NotNull] = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class TagRead(BaseSchema):
    id: int
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime
