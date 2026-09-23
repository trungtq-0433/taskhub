"""Tag DTOs."""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.constants import NAME_MIN_LENGTH, TAG_COLOR_LENGTH, TAG_NAME_MAX_LENGTH
from app.schemas.base import BaseSchema, NotNull

# #RGB is not accepted: one canonical form means clients never have to
# normalise before comparing.
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class TagCreate(BaseSchema):
    name: str = Field(min_length=NAME_MIN_LENGTH, max_length=TAG_NAME_MAX_LENGTH)
    color: str | None = Field(default=None, pattern=HEX_COLOR, max_length=TAG_COLOR_LENGTH)


class TagUpdate(BaseSchema):
    """All optional — see the note on `ProjectUpdate`."""

    # name maps to a NOT NULL column; color is nullable.
    name: Annotated[str | None, NotNull] = Field(
        default=None, min_length=NAME_MIN_LENGTH, max_length=TAG_NAME_MAX_LENGTH
    )
    color: str | None = Field(default=None, pattern=HEX_COLOR, max_length=TAG_COLOR_LENGTH)


class TagRead(BaseSchema):
    id: int
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime
