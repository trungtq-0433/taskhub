"""Standard response envelopes shared by every endpoint.

FastAPI's own convention is to return the resource model directly and put
errors under `detail`. This project wraps responses instead, so the shapes
below are the single definition of that contract — both for runtime
serialization and for the generated OpenAPI schema.
"""

from math import ceil
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class BaseSchema(BaseModel):
    """Base for every DTO: ORM-aware, strips unknown input fields."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class PaginationMeta(BaseModel):
    """Pagination block placed inside `meta` for list endpoints."""

    page: int = Field(ge=1, description="Current page, 1-based")
    per_page: int = Field(ge=1, description="Items per page")
    total: int = Field(ge=0, description="Total matching items")
    total_pages: int = Field(ge=0, description="Total number of pages")

    @classmethod
    def build(cls, *, page: int, per_page: int, total: int) -> Self:
        return cls(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=ceil(total / per_page) if per_page else 0,
        )


class ResponseEnvelope[T](BaseModel):
    """Success envelope: `{"data": ...}`, with `meta` only when it carries something."""

    data: T
    meta: dict[str, Any] | None = None

    @classmethod
    def of(cls, data: T, **meta: Any) -> Self:
        return cls(data=data, meta=meta or None)

    @model_serializer(mode="wrap")
    def _omit_empty_meta(self, handler: Any) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        if payload.get("meta") is None:
            payload.pop("meta", None)
        return payload


class PaginatedEnvelope[T](BaseModel):
    """Success envelope for collections, with pagination inside `meta`."""

    data: list[T]
    meta: PaginationMeta

    @classmethod
    def of(cls, items: list[T], *, page: int, per_page: int, total: int) -> Self:
        return cls(
            data=items,
            meta=PaginationMeta.build(page=page, per_page=per_page, total=total),
        )


class ErrorDetail(BaseModel):
    """One field-level or item-level cause behind an error."""

    field: str | None = Field(default=None, description="Dotted path to the offending field")
    message: str
    type: str | None = Field(default=None, description="Machine-readable cause")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable, machine-readable error code")
    message: str = Field(description="Human-readable summary")
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = Field(
        default=None, description="Correlation id, echoed in the X-Request-ID header"
    )


class ErrorEnvelope(BaseModel):
    """Failure envelope: `{"error": {"code", "message", "details", "request_id"}}`."""

    error: ErrorBody
