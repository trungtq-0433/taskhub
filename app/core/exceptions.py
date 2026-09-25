"""Domain exception hierarchy, expressed in RFC 9457 terms.

Services raise these; routers never build an error response by hand and do not
raise `HTTPException`. Each class fixes the three things a client reads: the
status, the `type` slug it branches on, and the `title` describing the kind of
problem. `detail` explains the one occurrence and may be reworded freely.

The split at 422 is deliberate. `validation` means the payload did not match
the schema; `business-rule-violation` means it did and the domain refused it
anyway. A client fixes the first by correcting a field, and the second by doing
something else entirely.
"""

from http import HTTPStatus

from app.schemas.problem import InvalidField


class AppError(Exception):
    """Base class for every expected application failure."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    problem_type: str = "internal-error"
    title: str = "Internal Server Error"
    detail: str = "An unexpected error occurred."
    headers: dict[str, str] | None = None

    def __init__(
        self,
        detail: str | None = None,
        *,
        problem_type: str | None = None,
        title: str | None = None,
        errors: list[InvalidField] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.detail
        self.problem_type = problem_type or self.problem_type
        self.title = title or self.title
        self.errors = errors or []
        self.headers = headers
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    problem_type = "not-found"
    title = "Not Found"
    detail = "The requested resource does not exist."


class ConflictError(AppError):
    """Unique constraint clash, duplicate slug, concurrent update, etc."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "conflict"
    title = "Conflict"
    detail = "The request conflicts with the current state of the resource."


class BusinessRuleError(AppError):
    """The payload is well-formed but the domain refuses it."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    problem_type = "business-rule-violation"
    title = "Business Rule Violation"
    detail = "The request was understood but is not allowed."


class InvalidStateError(AppError):
    """The resource exists but its current state forbids the operation."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "invalid-state"
    title = "Invalid State"
    detail = "The resource is not in a state that allows this operation."


class UnauthorizedError(AppError):
    """Missing, invalid, or expired credentials.

    RFC 6750 requires `WWW-Authenticate` on a 401 for bearer-token auth;
    without it a client has no signal for what kind of credential to retry
    with. Defaulted here so every raise site gets it for free — a fresh dict
    literal per instance (never a shared class-level mutable default), so a
    caller who overrides `headers` never touches what another instance sees.
    """

    status_code = HTTPStatus.UNAUTHORIZED
    problem_type = "unauthorized"
    title = "Unauthorized"
    detail = "Authentication is required."

    def __init__(
        self,
        detail: str | None = None,
        *,
        problem_type: str | None = None,
        title: str | None = None,
        errors: list[InvalidField] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            detail,
            problem_type=problem_type,
            title=title,
            errors=errors,
            headers=headers if headers is not None else {"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    problem_type = "forbidden"
    title = "Forbidden"
    detail = "You do not have access to this resource."


class ServiceUnavailableError(AppError):
    """A downstream dependency (database, cache, third party) is not reachable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    problem_type = "service-unavailable"
    title = "Service Unavailable"
    detail = "A downstream dependency is unavailable."
