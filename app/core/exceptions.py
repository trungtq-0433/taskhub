"""Domain exception hierarchy.

Services raise these; routers never build HTTP errors by hand. Each class
pairs an HTTP status with a stable `code` that clients can branch on, so the
wire contract does not drift when a message is reworded.

Note the deliberate split at 422: `validation_error` means the payload did not
match the schema, `business_rule_violation` means it did but the domain
refused it anyway. Clients need to tell those apart.
"""

from http import HTTPStatus

from app.schemas.base import ErrorDetail


class AppError(Exception):
    """Base class for every expected application failure."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or []
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    """Unique constraint clash, duplicate slug, concurrent update, etc."""

    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "Resource conflict."


class BusinessRuleError(AppError):
    """The payload is well-formed but the domain refuses it."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "business_rule_violation"
    message = "The request could not be processed."


class InvalidStateError(AppError):
    """The resource exists but its current state forbids the operation."""

    status_code = HTTPStatus.CONFLICT
    code = "invalid_state"
    message = "The resource is not in a state that allows this operation."


class UnauthorizedError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    message = "Authentication required."


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"
    message = "You do not have access to this resource."


class ServiceUnavailableError(AppError):
    """A downstream dependency (database, cache, third party) is not reachable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A downstream dependency is unavailable."
