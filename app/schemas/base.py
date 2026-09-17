"""Shared DTO building blocks.

Responses are not enveloped: a route returns its model directly and the HTTP
status carries the outcome, which is what FastAPI and its generated clients
expect. Collections are the one exception — they need somewhere to put the
pagination counts, so they use `Page[T]` rather than a bare list.
"""

from math import ceil
from typing import Self

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base for every DTO: ORM-aware, strips unknown input fields."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


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
