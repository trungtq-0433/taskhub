# API Conventions

How this service shapes responses, reports errors, and where each concern lives.
Every phase after the foundation is expected to follow this document.

## 1. Response shape

Success — `meta` only appears when it carries something:

```json
{ "data": { "id": 1, "title": "Ship v1" } }
{ "data": [ ... ], "meta": { "page": 1, "per_page": 20, "total": 57, "total_pages": 3 } }
```

Failure — one shape, always:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [{ "field": "email", "message": "value is not a valid email address", "type": "value_error" }],
    "request_id": "9f2c1e8a4b7d4c31a0e5f6d7c8b9a012"
  }
}
```

Build them with `ResponseEnvelope.of(...)` / `PaginatedEnvelope.of(...)` from
`app/schemas/base.py`. Routers never assemble a dict by hand.

### A note for people arriving from Rails

Idiomatic FastAPI does **not** envelope. A route returns the model, and errors
come back as `{"detail": ...}` in whatever shape raised them. This project
enveloped deliberately, so two things follow that a Rails serializer gives you
for free and FastAPI does not:

- **The envelope must be declared, not just returned.** `response_model=ResponseEnvelope[TaskRead]`
  is what keeps `/docs` honest. Return the envelope without declaring it and the
  generated schema lies to every client that reads it.
- **Overriding the error shape means overriding the docs too.** FastAPI hardcodes
  `HTTPValidationError` into the OpenAPI schema for 422. `DEFAULT_ERROR_RESPONSES`
  in `app/core/handlers.py` replaces it app-wide.

There is no `rescue_from` and no `before_action`. The equivalents are the
exception handlers in `app/core/handlers.py` and FastAPI dependencies.

## 2. Raising errors

Services raise domain exceptions from `app/core/exceptions.py`. Routers do not
raise `HTTPException`, and nothing builds a `JSONResponse` for an error.

| Exception | Status | `code` |
|---|---|---|
| `NotFoundError` | 404 | `not_found` |
| `ConflictError` | 409 | `conflict` |
| `InvalidStateError` | 409 | `invalid_state` |
| `BusinessRuleError` | 422 | `business_rule_violation` |
| `UnauthorizedError` | 401 | `unauthorized` |
| `ForbiddenError` | 403 | `forbidden` |
| `ServiceUnavailableError` | 503 | `service_unavailable` |

```python
raise ConflictError("Email already registered.", code="duplicate_email")
```

`code` is the client's contract — it may be narrowed per call site as above, but
never reworded casually. `message` is for humans and may change freely.

**The 422 split matters.** `validation_error` means the payload did not match the
schema; `business_rule_violation` means it did, and the domain refused it anyway.
A client retries the first by fixing a field, and the second by doing something
else entirely.

## 3. What the handlers guarantee

Registered in `register_exception_handlers()`, narrowest type first:

- `AppError` → its own status and code.
- `RequestValidationError` → 422, one `details` entry per offending field, dotted path.
- `IntegrityError` → 409, not a 500. A unique-constraint clash is the client's problem.
- `SQLAlchemyError` → 500 `database_error`, cause logged, never returned.
- `HTTPException` → reshaped into the envelope (this catches FastAPI's own 404/405).
- `Exception` → 500 `internal_error`. The cause reaches the log only, unless `DEBUG`.

Two things worth knowing:

- Responses are rendered through `jsonable_encoder`, so a `details` entry may carry
  a UUID, `datetime` or `Decimal` without blowing up in `JSONResponse`.
- With `DEBUG=true`, Starlette intercepts unhandled exceptions ahead of our handler
  and returns an HTML traceback instead of the envelope. That is a local-development
  convenience, and why the 500 test builds an app with `DEBUG` off.

## 4. Correlation id

`RequestIDMiddleware` honours an inbound `X-Request-ID` or mints one, echoes it on
every response, and every error envelope repeats it in `request_id`. That value is
what ties a user's screenshot to a log line.

Read it anywhere with `get_request_id()`. Inside an exception handler, pass the
request — `get_request_id(request)` — because the context variable is already
unwound by the time Starlette's server-error handler runs.

## 5. Where logic lives

```
router      routing, dependency injection, response shaping — no business logic
service     business rules, transaction boundaries, locking
repository  SQLAlchemy queries, no business rules
schema      request/response DTOs; responses exclude sensitive fields
```

The request-scoped session from `SessionDep` is **not** committed by the dependency.
Transactions are opened and committed in the service layer, which is where row
locking belongs.
