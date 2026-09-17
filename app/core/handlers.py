"""Global exception handlers producing the standard error envelope.

FastAPI would otherwise answer with `{"detail": ...}` in three different
shapes — a string for `HTTPException`, a list for validation errors, nothing
at all for an unhandled crash. Everything below funnels those into one shape
so a client only ever parses `{"error": {...}}`.
"""

import logging
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
from app.schemas.base import ErrorBody, ErrorDetail, ErrorEnvelope

logger = logging.getLogger(__name__)

# Only where the HTTP phrase is not the code we want to publish.
_CODE_OVERRIDES: dict[int, str] = {
    HTTPStatus.UNPROCESSABLE_ENTITY: "validation_error",
    HTTPStatus.TOO_MANY_REQUESTS: "rate_limited",
    HTTPStatus.INTERNAL_SERVER_ERROR: "internal_error",
}


def error_code_for(status_code: int) -> str:
    """Derive a stable error code from a status with no domain exception behind it."""
    if status_code in _CODE_OVERRIDES:
        return _CODE_OVERRIDES[status_code]
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        return "error"


def _envelope(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    """Render the error envelope.

    `jsonable_encoder` rather than `model_dump()`: details may one day carry a
    UUID, Decimal or datetime, and `JSONResponse` cannot serialize those.
    """
    payload = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
            request_id=get_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Domain errors raised by the service layer — expected, so logged quietly."""
    if exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        logger.error("%s: %s", exc.code, exc.message)
    return _envelope(request, exc.status_code, exc.code, exc.message, exc.details)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException from FastAPI itself (404, 405) or from a dependency."""
    code = error_code_for(exc.status_code)
    detail = exc.detail
    message = detail if isinstance(detail, str) else HTTPStatus(exc.status_code).phrase
    structured = not isinstance(detail, str) and detail is not None
    details = [ErrorDetail(message=str(detail))] if structured else []
    return _envelope(request, exc.status_code, code, message, details)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic payload validation — one detail entry per offending field."""
    details = [
        ErrorDetail(
            field=_field_path(error.get("loc", ())),
            message=str(error.get("msg", "Invalid value")),
            type=str(error["type"]) if error.get("type") else None,
        )
        for error in exc.errors()
    ]
    return _envelope(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "validation_error",
        "Request validation failed.",
        details,
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Constraint violations are a client conflict, not a server fault."""
    logger.warning("Integrity error: %s", exc.orig or exc)
    return _envelope(
        request,
        HTTPStatus.CONFLICT,
        "conflict",
        "The request conflicts with the current state of the database.",
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error", exc_info=exc)
    return _envelope(
        request, HTTPStatus.INTERNAL_SERVER_ERROR, "database_error", "A database error occurred."
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last line of defence — the cause goes to the log, never to the client."""
    logger.exception("Unhandled exception", exc_info=exc)
    message = str(exc) if settings.debug else "An unexpected error occurred."
    return _envelope(request, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", message)


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
    app.add_exception_handler(Exception, unhandled_exception_handler)


# OpenAPI: without this, the schema keeps advertising FastAPI's default
# `{"detail": [...]}` for 422 while the handlers above actually return the
# error envelope. Applied app-wide so every route documents the truth.
DEFAULT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    HTTPStatus.UNPROCESSABLE_ENTITY: {
        "model": ErrorEnvelope,
        "description": "Request validation failed",
    },
    HTTPStatus.INTERNAL_SERVER_ERROR: {
        "model": ErrorEnvelope,
        "description": "Unexpected server error",
    },
}
