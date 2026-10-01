"""Shared DTO building blocks.

Responses are not enveloped: a route returns its model directly and the HTTP
status carries the outcome, which is what FastAPI and its generated clients
expect. Collections are the one exception — they need somewhere to put the
pagination counts, so they use `Page[T]` rather than a bare list.
"""

from math import ceil
from typing import Any, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base for every DTO: ORM-aware, strips unknown input fields."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


def _refuse_null(value: Any) -> Any:
    if value is None:
        raise ValueError("cannot be null — omit the field to leave it unchanged")
    return value


NotNull = BeforeValidator(_refuse_null)
"""Reject an explicit null on a PATCH field whose column is NOT NULL.

Omitting a field means "leave it alone". Sending null asks to store null,
which a NOT NULL column refuses — and without this the request reaches the
database and comes back as a 409, telling the client that someone else changed
the row and a retry might help. It will not.

Wrap the whole optional type, not the inner one:

    name: Annotated[str | None, NotNull] = None     # refuses null
    name: Annotated[str, NotNull] | None = None     # accepts it

The second form gives Pydantic a `None` branch of the union to succeed on, so
the validator never gets to decide. A default is not validated, so an omitted
field never reaches this either way.
"""


def _lowercase(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


CaseInsensitive = BeforeValidator(_lowercase)
"""Lowercase a query value before it reaches enum validation:
`?status=TODO` matches the stored, lowercase `TaskStatus.TODO` instead of 422ing.

Query params only — request bodies stay exact-case, so this is never applied
to a schema field. Lives here rather than in a filter DTO's own module because
both `TaskFilter` fields need it: a `BeforeValidator` inside `Annotated[...]`
runs as part of the field's own validation, before `fastapi_filter.FilterDepends`
ever calls a model validator, which is what makes it work at all — `FilterDepends`
turns each filter field into its own `Query(...)` parameter typed by the field's
bare annotation and validates that parameter before the model as a whole is ever
built, so a `field_validator(mode="before")` on the class never gets a turn
(verified against fastapi-filter 3.0.0 / FastAPI 0.141.1: `?status=TODO` 422s
that way, and 200s through the annotation).
"""


class Page[T](BaseModel):
    """A page of results, with the counts a client needs to navigate."""

    items: list[T]
    total: int = Field(ge=0, description="Total matching items")
    page: int = Field(ge=1, description="Current page, 1-based")
    size: int = Field(ge=1, description="Items per page")
    pages: int = Field(ge=0, description="Total number of pages")

    @classmethod
    def of(cls, items: list[T], *, total: int, page: int, size: int) -> Self:
        return cls(
            items=items,
            total=total,
            page=page,
            size=size,
            pages=ceil(total / size) if size else 0,
        )
