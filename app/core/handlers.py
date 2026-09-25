"""Global exception handlers rendering RFC 9457 Problem Details.

Left alone, FastAPI reports failures as `detail` in three different shapes — a
string for `HTTPException`, a list of objects for validation errors, and
nothing at all for an unhandled crash. Everything below funnels them into one
documented shape, served as `application/problem+json`.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.middleware import get_request_id
from app.schemas.problem import (
    PROBLEM_MEDIA_TYPE,
    PROBLEM_SCHEMA,
    InvalidField,
    ProblemDetail,
    problem_type_uri,
)

logger = logging.getLogger(__name__)


def _problem_slug(status_code: int) -> str:
    """Derive a `type` slug from a status with no domain exception behind it."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "-")
    except ValueError:
        return "error"


def _problem(
    request: Request,
    status_code: int,
    slug: str,
    title: str,
    detail: str | None = None,
    errors: list[InvalidField] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Render a problem document.

    `jsonable_encoder` rather than `model_dump()`: an `errors` entry may carry a
    UUID, `datetime` or `Decimal`, and `JSONResponse` cannot serialize those.
    `headers` carries response headers the raiser needs on the wire — e.g. the
    `Allow` FastAPI attaches to a 405, or `WWW-Authenticate` on a 401 — which
    otherwise have nowhere to go once the exception is replaced by this body.
    """
    problem = ProblemDetail(
        type=problem_type_uri(slug),
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        errors=errors or None,
        request_id=get_request_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(problem, exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Domain errors raised by the service layer — expected, so logged quietly."""
    if exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        logger.error("%s: %s", exc.problem_type, exc.detail)
    return _problem(
        request, exc.status_code, exc.problem_type, exc.title, exc.detail, exc.errors, exc.headers
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException from FastAPI itself (404, 405) or from a dependency."""
    status = HTTPStatus(exc.status_code)

    # Starlette annotates `detail` as str, but FastAPI's subclass widens it to
    # Any and callers do pass dicts. Typed as object so both branches stay
    # reachable to the type checker as well as at runtime.
    detail: object = exc.detail
    text = detail if isinstance(detail, str) else None if detail is None else str(detail)

    # Starlette defaults `detail` to the status phrase. RFC 9457 wants `detail`
    # to describe this occurrence, so a copy of the title earns nothing — drop
    # it and let the member be absent.
    if text == status.phrase:
        text = None

    # `HTTPException.headers` may be None — Starlette's own 405 sets `Allow`
    # here, and `OAuth2PasswordBearer` sets `WWW-Authenticate`; both were
    # silently dropped before this handler forwarded them.
    return _problem(
        request,
        exc.status_code,
        _problem_slug(exc.status_code),
        status.phrase,
        text,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Payload validation — one `errors` entry per offending field."""
    errors = [
        InvalidField(
            field=_field_path(error.get("loc", ())),
            message=str(error.get("msg", "Invalid value")),
            type=str(error["type"]) if error.get("type") else None,
        )
        for error in exc.errors()
    ]
    return _problem(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "validation",
        "Validation Failed",
        "The request payload did not match the expected schema.",
        errors,
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Constraint violations are a client conflict, not a server fault."""
    logger.warning("Integrity error: %s", exc.orig or exc)
    return _problem(
        request,
        HTTPStatus.CONFLICT,
        "conflict",
        "Conflict",
        "The request conflicts with the current state of the database.",
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error", exc_info=exc)
    return _problem(
        request,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "database-error",
        "Internal Server Error",
        "A database error occurred.",
    )


async def connection_error_handler(request: Request, exc: OSError) -> JSONResponse:
    """A backing service could not be reached.

    asyncpg raises the asyncio error unwrapped — `ConnectionRefusedError`,
    `socket.gaierror`, `TimeoutError` — so `SQLAlchemyError` never sees it and
    the catch-all below would answer 500. It belongs here rather than in each
    service: the condition is identical everywhere, and 503 is what tells a
    load balancer to take the instance out of rotation and a client that
    retrying is worth it.
    """
    logger.error("Dependency unreachable: %r", exc)
    return _problem(
        request,
        HTTPStatus.SERVICE_UNAVAILABLE,
        "service-unavailable",
        "Service Unavailable",
        "A downstream dependency is unavailable.",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last line of defence — the cause goes to the log, never to the client."""
    logger.exception("Unhandled exception", exc_info=exc)
    detail = str(exc) if settings.debug else "An unexpected error occurred."
    return _problem(
        request,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "internal-error",
        "Internal Server Error",
        detail,
    )


def _field_path(loc: tuple[int | str, ...]) -> str | None:
    """Turn a Pydantic error location into a dotted path, dropping the source segment."""
    parts = [str(part) for part in loc if part not in ("body", "query", "path", "header")]
    return ".".join(parts) or None


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler above, narrowest exception type first."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, integrity_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(OSError, connection_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)


# OpenAPI: FastAPI advertises its own HTTPValidationError for 422 and says
# nothing about the other failures. Declared app-wide so the schema documents
# the problem document that is actually returned, with the right media type.
#
# Routers reuse this for their per-route 404/409. Declaring {"model":
# ProblemDetail} instead looks equivalent and is not: FastAPI then documents
# application/json, while the handler answers application/problem+json.
PROBLEM_CONTENT = {PROBLEM_MEDIA_TYPE: {"schema": PROBLEM_SCHEMA}}

DEFAULT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    HTTPStatus.UNPROCESSABLE_ENTITY: {
        "description": "Validation failed",
        "content": PROBLEM_CONTENT,
    },
    HTTPStatus.INTERNAL_SERVER_ERROR: {
        "description": "Unexpected server error",
        "content": PROBLEM_CONTENT,
    },
}
