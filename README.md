# TaskHub API

A task and project management API built on FastAPI, SQLAlchemy 2.0 async and
PostgreSQL, laid out in loosely coupled layers along DDD lines.

> **Status: foundation only.** The response contract, database wiring and error
> handling are in place and exercised by tests. Entities, repositories and
> endpoints are the phases that follow — `app/models/`, `app/repositories/` and
> `app/services/` are still empty.

## Stack

| | |
|---|---|
| Runtime | Python 3.12 (pinned — see below) |
| Framework | FastAPI, Pydantic v2 |
| Database | PostgreSQL 16 via SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic (async, wired up in phase 2) |
| Tooling | uv, ruff, mypy (strict), pytest |

The interpreter is pinned in `.python-version` to match the runtime image. uv
would otherwise resolve to the newest Python on the machine, and the two
environments would quietly diverge.

## Quick start

With Docker — the API waits on a Postgres healthcheck rather than racing it:

```bash
cp .env.example .env
docker compose up --build
```

Against a local interpreter, with only the database in a container:

```bash
cp .env.example .env
docker compose up -d db
uv sync
uv run uvicorn app.main:app --reload
```

Then:

| | |
|---|---|
| Liveness | `GET /api/v1/health` |
| Readiness (checks the database) | `GET /api/v1/ready` |
| OpenAPI UI | `/docs` · `/redoc` · `/openapi.json` |

If port 5432 is already taken on your machine, set `POSTGRES_PORT` in `.env` —
it only moves the host-side binding, not the port inside the network.

## Layout

```
app/
├── api/routers/    routing, dependency injection, response shaping
├── services/       business rules, transaction boundaries, locking
├── repositories/   SQLAlchemy queries, no business rules
├── schemas/        request and response DTOs
├── models/         SQLAlchemy entities
└── core/           config, database, exceptions, handlers, middleware
```

The rule that keeps the layers apart: **routers hold no business logic and
repositories hold no business rules.** A router injects a service and shapes the
response; a service decides what is allowed and owns the transaction; a
repository only knows how to ask the database.

One consequence worth knowing up front: the request-scoped session from
`SessionDep` rolls back on failure but **never commits**. Committing belongs to
the service layer, because that is also where row locking will live, and the two
cannot be separated without creating races.

## Response contract

A route returns its model; the HTTP status carries the outcome. No envelope:

```json
GET /api/v1/tasks/1  →  200
{ "id": 1, "title": "Ship v1", "status": "open" }
```

Collections need somewhere to put counts, so they use `Page[T]`:

```json
GET /api/v1/tasks  →  200
{ "items": [ ... ], "total": 57, "page": 1, "size": 20, "pages": 3 }
```

### Errors

Failures are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem documents,
served as `application/problem+json` — one shape for every failure, standardised
rather than invented here:

```json
POST /api/v1/tasks  →  422
{
  "type": "urn:taskhub:problem:validation",
  "title": "Validation Failed",
  "status": 422,
  "detail": "The request payload did not match the expected schema.",
  "instance": "/api/v1/tasks",
  "errors": [{ "field": "title", "message": "String should have at least 1 character", "type": "string_too_short" }],
  "request_id": "9f2c1e8a4b7d4c31a0e5f6d7c8b9a012"
}
```

`type` identifies the kind of problem and is the only part clients should branch
on; `detail` explains the single occurrence and may be reworded freely. `errors`
and `request_id` are extension members, which the spec permits.

Left to itself FastAPI reports failures as `detail` in three different shapes — a
string, a list of objects, or nothing at all when something crashes. Handlers
funnel all of them into the document above.

Services raise domain exceptions from `app/core/exceptions.py`. Nothing in the
codebase builds an error response by hand, and routers do not raise
`HTTPException`.

| Exception | Status | `type` suffix |
|---|---|---|
| `NotFoundError` | 404 | `not-found` |
| `ConflictError` | 409 | `conflict` |
| `InvalidStateError` | 409 | `invalid-state` |
| `BusinessRuleError` | 422 | `business-rule-violation` |
| `UnauthorizedError` | 401 | `unauthorized` |
| `ForbiddenError` | 403 | `forbidden` |
| `ServiceUnavailableError` | 503 | `service-unavailable` |

The split at 422 is deliberate: `validation` means the payload did not match the
schema, `business-rule-violation` means it did and the domain refused it anyway.
A client fixes the first by correcting a field, and the second by doing something
else entirely.

Database constraint violations answer 409 rather than 500 — a unique-constraint
clash is the client's problem, not a server fault. Unhandled exceptions answer
500 with the cause written to the log and never to the response body.

### Request id

Every response carries `X-Request-ID`, honouring an inbound one or minting it,
and every problem document repeats it. That single value is what connects a
user's screenshot to a log line.

## Quality gate

```bash
uv run ruff check .    # lint
uv run ruff format .   # formatting
uv run mypy            # types — strict, across app/ and tests/
uv run pytest          # tests
```

mypy runs strict with the pydantic plugin, and it earns the cost: on its first
run it found a branch in the `HTTPException` handler that was dead to the type
checker but reachable at runtime. Lint did not see it and no test covered it.

## Further reading

`docs/configuration.md` covers how settings resolve and which variables are required.
`docs/api-conventions.md` holds the full contract — what each handler
guarantees, how the correlation id survives Starlette's error path, and the
conventions every later phase is expected to follow.
