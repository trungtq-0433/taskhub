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

With Docker — the API waits on a Postgres healthcheck rather than racing it.
Compose supplies the container's own `DATABASE_URL`, so the placeholder in
`.env` is not used on this path:

```bash
cp .env.example .env
docker compose up --build
```

Against a local interpreter, with only the database in a container. Here
`DATABASE_URL` **must** be filled in with real values — `.env.example` ships
placeholders:

```bash
cp .env.example .env
$EDITOR .env          # DATABASE_URL=postgresql+asyncpg://taskhub:taskhub@localhost:5432/taskhub
docker compose up -d db
uv sync
uv run uvicorn app.main:app --reload
```

The API serves `/docs`, `/redoc` and `/openapi.json`. There are no resource
endpoints yet — those arrive with the entities.

If port 5432 is already taken on your machine, create a
`docker-compose.override.yml` — compose reads it automatically and git ignores
it, so it stays yours:

```yaml
services:
  db:
    ports: !override        # replaces the port list instead of adding to it
      - "5433:5432"
```

Then point `DATABASE_URL` in `.env` at the same host port. Only the host side
moves; inside the compose network the database still listens on 5432.

Settings, the required variables and what happens when one is missing:
[docs/configuration.md](docs/configuration.md).

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

## Response contract

A route returns its model and the HTTP status carries the outcome — no envelope.
Failures are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem
documents, served as `application/problem+json`:

```json
GET /api/v1/tasks/1   →  200   { "id": 1, "title": "Ship v1", "status": "open" }

GET /api/v1/tasks/99  →  404   { "type": "urn:taskhub:problem:task-not-found",
                                 "title": "Not Found", "status": 404,
                                 "detail": "Task 99 does not exist.",
                                 "instance": "/api/v1/tasks/99",
                                 "request_id": "9f2c1e8a…" }
```

`type` is the part clients branch on. Every response also carries an
`X-Request-ID` header, repeated in the problem body, which is what ties a user's
screenshot to a log line.

The full contract — the domain exception table, what each handler guarantees,
and the reasoning behind the choices — is
[docs/api-conventions.md](docs/api-conventions.md). Every phase after this one
is expected to follow it.

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
