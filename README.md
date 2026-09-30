# TaskHub API

A task and project management API built on FastAPI, SQLAlchemy 2.0 async and
PostgreSQL, laid out in loosely coupled layers along DDD lines.

> **Status:** projects and tags are full CRUD. Tasks are list and create only
> under a project — no update or delete endpoint yet — plus a top-level list
> across every project with `status`/`priority` filters, and a bookmark an
> active logged-in user can add to any task (no un-bookmark, no listing
> bookmarks back). Users register, log in with a JWT, and can read or update
> their own profile; a public, read-only profile lookup stays open to anyone.
> Admin and project-manager guards exist (`app/api/permissions.py`) but guard
> no route yet. All of it sits on the same response contract, database wiring
> and error handling, and all of it is exercised by tests.

## Stack

| | |
|---|---|
| Runtime | Python 3.12 (pinned — see below) |
| Framework | FastAPI, Pydantic v2 |
| Database | PostgreSQL 16 via SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic (async) |
| Tooling | uv, ruff, mypy (strict), pytest |

The interpreter is pinned in `.python-version` to match the runtime image. uv
would otherwise resolve to the newest Python on the machine, and the two
environments would quietly diverge.

`fastapi-filter` carries pins of its own, tighter than this project's floor:
`fastapi<1.0` and `SQLAlchemy<2.1`. Both already sit inside those bounds, but a
future bump to either has to clear fastapi-filter's ceiling too, not just the
version this project asks for in `pyproject.toml`.

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

The API serves projects and tags (full CRUD), tasks nested under a project
(list and create) plus a top-level task list across every project and a
bookmark endpoint, user registration/login/profile management, and a public
read-only profile lookup, all under `/api/v1`. Browse them at `/docs`, which
also renders every error response each route can return. Those three doc
routes are served everywhere except production.

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

`ENVIRONMENT` and `DATABASE_URL` have no defaults — miss either and the
process refuses to start, naming the variable, rather than running on a guess.
`app/core/config.py` is the whole of the configuration.

Adding a model — or a Core `Table` with no declarative class, such as an
association table — follows the same rule: write it, **import it in
`app/models/__init__.py`**, then `alembic revision --autogenerate`. Read the
generated file before applying it — anything Alembic cannot see it believes
you deleted, and it will write a migration that DROPs the table without
erroring.

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
GET /api/v1/projects/1   →  200   { "id": 1, "name": "Ship v1", "description": null,
                                    "status": "active", "created_at": "2026-09-21T09:00:10Z",
                                    "updated_at": "2026-09-21T09:00:10Z", "total_tasks": 3 }

GET /api/v1/projects/99  →  404   { "type": "urn:taskhub:problem:project-not-found",
                                    "title": "Not Found", "status": 404,
                                    "detail": "Project 99 does not exist.",
                                    "instance": "/api/v1/projects/99",
                                    "request_id": "9f2c1e8a…" }
```

`type` is the part clients branch on. Every response also carries an
`X-Request-ID` header, repeated in the problem body, which is what ties a user's
screenshot to a log line. A problem document also forwards whatever response
headers the failure itself carries — `WWW-Authenticate` on a 401,
`Allow` on a 405 — rather than dropping them when the body is replaced.

Domain exceptions live in `app/core/exceptions.py`, one class per kind, each
carrying the status and the `type` suffix it answers with. The handlers that
render them are in `app/core/handlers.py`; their docstrings say what each
guarantees.

## Authentication

JWT bearer tokens, issued by the API itself — no third-party identity provider.

| Method | Path | |
|---|---|---|
| `POST` | `/api/v1/users/register` | Create a user: `{username, password, full_name?}` → `201` with the new `UserRead`. |
| `POST` | `/api/v1/users/login` | Exchange a username and password, **form-encoded**, for an access token. |
| `GET` | `/api/v1/users/me` | The authenticated user, as `UserRead`. Requires `Authorization: Bearer <token>`. |
| `PUT` | `/api/v1/users/me` | Replace `full_name` (`null` clears it, the key is required). Username is immutable. Requires the same header. |

```bash
curl -s -X POST localhost:8000/api/v1/users/register \
  -H 'Content-Type: application/json' \
  -d '{"username": "trung", "password": "correct-horse-battery"}'

TOKEN=$(curl -s -X POST localhost:8000/api/v1/users/login \
  -d 'username=trung&password=correct-horse-battery' | jq -r .access_token)

curl -s localhost:8000/api/v1/users/me -H "Authorization: Bearer $TOKEN"
```

`JWT_SECRET_KEY` is required, like `DATABASE_URL` — the process refuses to
start without it. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`user.hashed_password` is `NOT NULL` with no default, so on a database that
already holds users created by hand before this endpoint existed, the
migration that added the column fails with Postgres's own "column contains
null values" error — there is no plaintext left to hash for a row it never
saw. Clear those rows first, then register through the API instead:

```sql
DELETE FROM "user";
```

`task.assignee_id` and `project.owner_id` are both `ON DELETE SET NULL`, so
existing tasks and projects survive that delete untouched.

There is no rate limiting or lockout on `/users/login`: brute-forcing a
password and running up bcrypt's CPU cost with repeated failed attempts are
both unmitigated in the app. Put a proxy or gateway that rate-limits that path
in front before exposing it publicly.

`user.role` (`user`/`admin`, default `user`) and `user.is_active` (default
`true`) are set only through SQL — there is no endpoint for either, and
neither appears in `UserRead`. Both are read from the database row on every
request, never from the JWT, so a change takes effect on the account's very
next request rather than waiting for the old token to expire. `POST
/users/login` is unchanged: a disabled account can still obtain a token.
Today only `POST /api/v1/tasks/{task_id}/bookmark` checks `is_active` (403
`inactive-user`, via `ActiveUserDep`) — `GET`/`PUT /users/me` accept any valid
token regardless of `is_active`.

```sql
UPDATE "user" SET role = 'admin' WHERE username = '...';
UPDATE "user" SET is_active = false WHERE username = '...';  -- true to restore
```

`verify_admin_role` (403 `admin-required`) and `verify_project_manager`
(owner or admin; 404 `project-not-found` for a missing project, then 403
`project-manager-required` — a project with no owner is manageable by admins
only) exist in `app/api/permissions.py` but guard no route yet: creating,
updating or deleting a project or a tag is not actually protected by them
today.

## Tasks

| Method | Path | |
|---|---|---|
| `GET` | `/api/v1/tasks` | Every task, across every project, filterable by `status`/`priority`. Public. |
| `GET` | `/api/v1/projects/{project_id}/tasks` | One project's tasks, no filters. Public. `404` if the project does not exist. |
| `POST` | `/api/v1/projects/{project_id}/tasks` | Create a task in a project. `priority` defaults to `medium`. |
| `POST` | `/api/v1/tasks/{task_id}/bookmark` | Bookmark a task. Requires `Authorization: Bearer <token>` for an active account. |

`GET /api/v1/tasks` takes `status` and `priority` as equality filters that
combine with AND; either or both may be omitted. Both are case-insensitive —
`?status=TODO` matches the stored, lowercase `todo` — and a value neither
enum recognizes is a `422` naming the field and the values it does accept.
The nested `GET /api/v1/projects/{project_id}/tasks` takes neither filter; it
always lists everything in that project.

```bash
curl -s "localhost:8000/api/v1/tasks?status=todo&priority=high"
```

Both task lists are paginated: `page` starts at 1 with no upper bound, `size`
is 1-100 and defaults to 50 when omitted. That is wider than `/api/v1/projects`
and `/api/v1/tags`, which default to `size=20` and cap `page` at 100000 — the
task lists and the older list routes are paginated by two different libraries
under the hood, and were never meant to share a default. One consequence of
having no ceiling on the task lists: a `page` whose offset overflows
Postgres's own bigint answers `500`, not `422` — a known, accepted edge (the
overflow starts past `page` ≈ 1.8×10¹⁷ at the default `size`):

```bash
curl -s "localhost:8000/api/v1/tasks?page=10000000000000000"    # 200, empty page
curl -s "localhost:8000/api/v1/tasks?page=1000000000000000000"  # 500, offset overflows bigint
```

(`?page=1e18` is a plain `422` — scientific notation is not an integer.)

Every task carries a `priority` of `low`, `medium` or `high`, defaulting to
`medium` when a create request leaves it out:

```bash
curl -s -X POST localhost:8000/api/v1/projects/1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title": "Ship it", "priority": "high"}'
```

Bookmarking needs a token from `/api/v1/users/login`, for an account that is
still active — a disabled account's token gets `403` (`inactive-user`), not
the `401` a missing or invalid token gets:

```bash
curl -s -X POST localhost:8000/api/v1/tasks/1/bookmark \
  -H "Authorization: Bearer $TOKEN"
```

`201` returns `{"task_id": 1, "created_at": "..."}`. The same user bookmarking
the same task again is a `409` (`already-bookmarked`), not a silent no-op; an
unknown task is `404` (`task-not-found`). There is no un-bookmark and no
listing your bookmarks back yet — only the one `POST`.

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

**`pytest` needs Postgres running** (`docker compose up -d db`). It creates a
separate `taskhub_test` database on first run and applies the migrations to it —
your development data is never touched, and `TEST_DATABASE_URL` overrides the
target. Each test runs inside a transaction that is rolled back afterwards, so
tests cannot see each other's writes even when they commit.
