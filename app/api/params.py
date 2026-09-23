"""Declarations every resource router shares.

Pagination bounds and error-response shapes were repeated in each router, which
means one of them eventually diverges: raise the page-size ceiling in one file
and two endpoints quietly disagree about what a valid request is. Declared once
here, they change in one place.
"""

from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, Field

from app.core.handlers import PROBLEM_CONTENT

ErrorResponses = dict[int | str, dict[str, Any]]


class Pagination(BaseModel):
    """The query parameters every list endpoint takes.

    A model rather than two annotated aliases, because the defaults have to be
    shared as well as the bounds. FastAPI refuses a default inside
    `Annotated[..., Query()]` — "`Query` default value cannot be set in
    `Annotated`; set the default value with `=` instead" — so aliases alone
    leave `page=1, size=20` to be retyped in the signature of every list route,
    and those literals then have to be changed together or not at all.

    `page` is bounded as well as `size`. Without a ceiling the computed offset
    overflows Postgres's bigint and the request dies as a 500 rather than being
    refused as a 422.
    """

    page: int = Field(default=1, ge=1, le=100_000, description="Page number, 1-based")
    size: int = Field(default=20, ge=1, le=100, description="Items per page")


PaginationDep = Annotated[Pagination, Query()]
"""The model read from the query string. Each field stays its own parameter in
the generated schema, so `?page=2&size=50` is unchanged on the wire."""

CONFLICT: ErrorResponses = {409: {"content": PROBLEM_CONTENT, "description": "Name already taken"}}


def not_found(resource: str) -> ErrorResponses:
    """404 for one resource kind.

    A route that can 404 has to say so: `DEFAULT_ERROR_RESPONSES` declares 422
    and 500 app-wide, and a schema silent about 404 tells a generated client
    the route cannot fail that way.
    """
    return {404: {"content": PROBLEM_CONTENT, "description": f"No such {resource}"}}
