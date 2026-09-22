# API Conventions

How this service shapes responses, reports errors, and where each concern lives.
Every phase after the foundation is expected to follow this document.

## 1. Responses are not enveloped

A route returns its model. The HTTP status carries the outcome.

```json
GET /api/v1/projects/1  →  200
{ "id": 1, "name": "Ship v1", "description": null, "status": "active",
  "created_at": "2026-09-21T09:00:10Z", "updated_at": "2026-09-21T09:00:10Z" }
```

This is what FastAPI is built around, and it keeps the generated OpenAPI schema —
and therefore every generated client — describing the resource itself rather than
a wrapper around it.

Collections are the one place that needs somewhere to put counts, so they use
`Page[T]` from `app/schemas/base.py`:

```json
GET /api/v1/projects  →  200
{ "items": [ ... ], "total": 57, "page": 1, "size": 20, "pages": 3 }
```

Declare it as the return annotation — `async def list_projects(...) -> Page[ProjectRead]`
— and FastAPI derives the response model from it. Nothing needs an explicit
`response_model=` unless the declared return type differs from what should be
serialized.

## 2. Failures are RFC 9457 problem documents

Left to itself, FastAPI reports failures as `detail` in three different shapes —
a string for `HTTPException`, a list of objects for validation errors, and
nothing at all when something crashes — so a client would need three branches to
parse one concept. The handlers funnel all of them into one shape, served as
`application/problem+json`:

```json
POST /api/v1/projects  →  422
{
  "type": "urn:taskhub:problem:validation",
  "title": "Validation Failed",
  "status": 422,
  "detail": "The request payload did not match the expected schema.",
  "instance": "/api/v1/projects",
  "errors": [{ "field": "name", "message": "String should have at least 1 character", "type": "string_too_short" }],
  "request_id": "9f2c1e8a4b7d4c31a0e5f6d7c8b9a012"
}
```

`type`, `title`, `status`, `detail` and `instance` are the standard's registered
members. `errors` and `request_id` are extension members, which RFC 9457 §3.2
permits.

What each member is for, in practice:

- **`type`** identifies the *kind* of problem and is the only part clients should
  branch on. It is a contract — narrow it per call site, never reword it casually.
- **`title`** is a human-readable summary of that kind, constant for a given `type`.
- **`detail`** explains *this one occurrence* and may be reworded freely. When it
  would only repeat the title, it is omitted instead.
- **`instance`** is the request path that produced the problem.

A URN is used for `type` rather than an `https://` URL. The spec encourages a
dereferenceable URI, but there is no documentation site to point at yet, and a URL
that 404s is worse than an honest identifier. When docs are published the scheme
changes and the suffix — the part clients match on — stays.

## 3. Raising errors

Services raise domain exceptions from `app/core/exceptions.py`. Routers do not
raise `HTTPException`, and nothing builds an error response by hand.

| Exception | Status | `type` suffix |
|---|---|---|
| `NotFoundError` | 404 | `not-found` |
| `ConflictError` | 409 | `conflict` |
| `InvalidStateError` | 409 | `invalid-state` |
| `BusinessRuleError` | 422 | `business-rule-violation` |
| `UnauthorizedError` | 401 | `unauthorized` |
| `ForbiddenError` | 403 | `forbidden` |
| `ServiceUnavailableError` | 503 | `service-unavailable` |

```python
raise ConflictError("Email already registered.", problem_type="duplicate-email")
```

The first argument is `detail`. Narrowing `problem_type` gives the client something
more specific than `conflict` to branch on, while the status and title stay put.

**The split at 422 matters.** `validation` means the payload did not match the
schema; `business-rule-violation` means it did, and the domain refused it anyway.
A client retries the first by fixing a field, and the second by doing something
else entirely.

## 4. What the handlers guarantee

Registered in `register_exception_handlers()`, narrowest type first:

- `AppError` → its own status, type and title.
- `RequestValidationError` → 422, one `errors` entry per offending field, dotted path.
- `IntegrityError` → 409, not a 500. A unique-constraint clash is the client's problem.
- `SQLAlchemyError` → 500 `database-error`, cause logged, never returned.
- `HTTPException` → converted to a problem document, which catches FastAPI's own 404/405.
- `OSError` → 503 `service-unavailable` — an unreachable database, not a generic
  500. See [Catching database failures](#catching-database-failures) below.
- `Exception` → 500 `internal-error`. The cause reaches the log only, unless `DEBUG`.

Two things worth knowing:

- Problems are rendered through `jsonable_encoder`, so an `errors` entry may carry
  a UUID, `datetime` or `Decimal` without blowing up in `JSONResponse`.
- With `DEBUG=true`, Starlette intercepts unhandled exceptions ahead of our handler
  and returns an HTML traceback instead of a problem document. That is a
  local-development convenience, and why the 500 test builds an app with `DEBUG` off.

`DEFAULT_ERROR_RESPONSES` declares the problem document app-wide in the OpenAPI
schema. Without it FastAPI keeps advertising its own `HTTPValidationError` for 422,
which is not what any route returns.

## 5. Correlation id

`RequestIDMiddleware` honours an inbound `X-Request-ID` or mints one, echoes it on
every response, and every problem document repeats it in `request_id`. That value is
what ties a user's screenshot to a log line.

Read it anywhere with `get_request_id()`. Inside an exception handler, pass the
request — `get_request_id(request)` — because the context variable is already
unwound by the time Starlette's server-error handler runs.

## 6. Where logic lives

```
router      routing, dependency injection, response shaping — no business logic
service     business rules, transaction boundaries, locking
repository  SQLAlchemy queries, no business rules
schema      request/response DTOs; responses exclude sensitive fields
```

The request-scoped session from `SessionDep` is **not** committed by the dependency.
Transactions are opened and committed in the service layer, which is where row
locking belongs.

**Routers do not take `SessionDep`.** They depend on a service, and the service
takes the session:

```python
class ProjectService:
    def __init__(self, session: SessionDep) -> None:
        self._session = session

ProjectServiceDep = Annotated[ProjectService, Depends()]
```

`Depends()` with no argument tells FastAPI to build the class and resolve its
`__init__` annotations, so the router never sees a session:

```python
async def get_project(project_id: int, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(await service.get(project_id))
```

A router reaching for a session directly is how query logic starts leaking
upward, so the rule has no exceptions — not even a one-line `SELECT 1`.

### Catching database failures

`except SQLAlchemyError` does **not** cover an unreachable database. When the
connection itself cannot be made, asyncpg raises the asyncio error unwrapped —
`ConnectionRefusedError`, `socket.gaierror`, `TimeoutError` — and SQLAlchemy
never sees it.

**Services do not catch it.** `connection_error_handler` maps `OSError` to
**503** `service-unavailable` centrally, because the condition is identical
behind every endpoint and per-service handling would be the same six lines
repeated. Left to the catch-all it would answer 500, which tells a load balancer
nothing and a client not to retry.

A service catches `SQLAlchemyError` only when it has something specific to say
about a *query* that failed — not to report the database being down.

## 7. Quality gate

Run all four before committing — they are cheap and catch different things:

```bash
uv run ruff check .        # lint
uv run ruff format .       # formatting
uv run mypy                # types, strict across app/ and tests/
uv run pytest              # tests
```

mypy runs in strict mode with the pydantic plugin. Keep it that way: it already
caught an unreachable branch in the `HTTPException` handler that lint and tests
both waved through. If a third-party stub forces an `# type: ignore`, pin the
error code (`# type: ignore[arg-type]`) so an unrelated error is never hidden —
`warn_unused_ignores` will tell you when one becomes obsolete.
