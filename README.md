# TaskHub API

A task and project management API built on FastAPI, SQLAlchemy 2.0 async and
PostgreSQL, laid out in loosely coupled layers along DDD lines.

> **Status:** projects and tags are full CRUD. Tasks are list and create only
> under a project — no update or delete endpoint yet — plus a top-level list
> across every project with `status`/`priority` filters, a bookmark an
> active logged-in user can add to any task (no un-bookmark, no listing
> bookmarks back), assigning a task to another active user (history recorded,
> no read endpoint), and comments: any active user can add one, and its
> author, an admin or the project's owner can delete it; when SMTP is
> configured, a new comment also emails the task's assignee. Users register
> (optionally with an email address), log in with a JWT, and can read or
> update their own profile; a public, read-only profile lookup stays open to
> anyone. The admin and
> project-manager guards (`app/api/permissions.py`) still guard no route; the
> comment guard next to them guards the comment delete. All of it sits on the
> same response contract, database wiring and error handling, and all of it
> is exercised by tests.

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

This also starts [Mailpit](https://mailpit.axllent.org), a local mail catcher
(SMTP on 1025, inbox at <http://localhost:8025>), and points the API at it, so
mail the API sends shows up there. See Email notifications. It starts a Redis
as well (6379) for the tag cache; see Tag cache.

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

Email is optional on this path: leave `SMTP_HOST` unset and none is sent. To
see it, run `docker compose up -d mailpit` and set `SMTP_HOST=localhost` in
`.env`. The tag cache is optional the same way: leave `REDIS_URL` unset, or run
`docker compose up -d redis` and set `REDIS_URL=redis://localhost:6379/0`.

The API serves projects and tags (full CRUD), tasks nested under a project
(list and create) plus a top-level task list across every project, a
bookmark endpoint, task assignment, comment create and delete (a new
comment emails the assignee), user registration/login/profile management, and a public
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
moves; inside the compose network the database still listens on 5432. The same
file can remap Mailpit's `1025:1025` and `8025:8025` the same way.

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
└── core/           config, database, exceptions, handlers, mail, redis, middleware
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
| `POST` | `/api/v1/users/register` | Create a user: `{username, password, full_name?, email?}` → `201` with the new `UserPrivate`. |
| `POST` | `/api/v1/users/login` | Exchange a username and password, **form-encoded**, for an access token. |
| `GET` | `/api/v1/users/me` | The authenticated user, as `UserPrivate`. Requires `Authorization: Bearer <token>`. |
| `PUT` | `/api/v1/users/me` | Replace `full_name` (`null` clears it, the key is required) and, optionally, `email`: omitted keeps it, `null` clears it, a value sets it. Username is immutable. Returns `UserPrivate`. Requires the same header. |

```bash
curl -s -X POST localhost:8000/api/v1/users/register \
  -H 'Content-Type: application/json' \
  -d '{"username": "trung", "password": "correct-horse-battery"}'

TOKEN=$(curl -s -X POST localhost:8000/api/v1/users/login \
  -d 'username=trung&password=correct-horse-battery' | jq -r .access_token)

curl -s localhost:8000/api/v1/users/me -H "Authorization: Bearer $TOKEN"
```

`email` is optional, stored lowercase and unique: a second account claiming
the same address is a `409` (`email-taken`), on register and on `PUT
/users/me` alike. It is the address comment notifications go to. It appears
only in `UserPrivate` — the register, `GET /users/me` and `PUT /users/me`
responses, which answer the caller about themselves — and never in
`UserRead`, so it is not on the public profile or on a user nested in another
response.

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
Today the bookmark, assign and both comment routes check `is_active` (403
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
today. `verify_comment_modifier` in the same file is wired, to the comment
delete (see Tasks).

## Tasks

| Method | Path | |
|---|---|---|
| `GET` | `/api/v1/tasks` | Every task, across every project, filterable by `status`/`priority`. Public. |
| `GET` | `/api/v1/projects/{project_id}/tasks` | One project's tasks, no filters. Public. `404` if the project does not exist. |
| `POST` | `/api/v1/projects/{project_id}/tasks` | Create a task in a project. `priority` defaults to `medium`. |
| `POST` | `/api/v1/tasks/{task_id}/bookmark` | Bookmark a task. Requires `Authorization: Bearer <token>` for an active account. |
| `POST` | `/api/v1/tasks/{task_id}/assign` | Assign a task to a user: `{assignee_id}` → `200` with the `TaskRead`. Same token requirement. |
| `POST` | `/api/v1/tasks/{task_id}/comments` | Comment on a task: `{content}` → `201` with the `CommentRead`. Same token requirement. |
| `DELETE` | `/api/v1/tasks/{task_id}/comments/{comment_id}` | Delete a comment → `204`. Its author, an admin or the project's owner. |

`GET /api/v1/tasks` takes `status` and `priority` as equality filters that
combine with AND; either or both may be omitted. Both are case-insensitive —
`?status=TODO` matches the stored, lowercase `todo` — and a value neither
enum recognizes is a `422` naming the field and the values it does accept.
The nested `GET /api/v1/projects/{project_id}/tasks` takes neither filter; it
always lists everything in that project.

```bash
curl -s "localhost:8000/api/v1/tasks?status=todo&priority=high"
```

Both task lists are paginated: `page` is 1-100000, `size` is 1-100 and
defaults to 50 when omitted. `/api/v1/projects` and `/api/v1/tags` share the
same `page` ceiling but default to `size=20` — the task lists and the older
list routes are paginated by two different libraries under the hood, and were
never meant to share a default. The `page` ceiling is not arbitrary: without
it the computed offset can pass Postgres's bigint, and the request dies as a
`500` instead of being refused as a `422`:

```bash
curl -s "localhost:8000/api/v1/tasks?page=100000"               # 200, empty page
curl -s "localhost:8000/api/v1/tasks?page=1000000000000000000"  # 422, page past the ceiling
```

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

Assigning, commenting and deleting a comment all need the same token, for an
account that is still active. `task_id`, `comment_id` and `assignee_id` on
these routes are bounded to `1..2147483647`; an id outside that is a `422`
(`validation`), not a `500`. The older routes keep an unbounded `int`.

```bash
curl -s -X POST localhost:8000/api/v1/tasks/1/assign -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"assignee_id": 2}'
```

Any active user can assign any task to any active user, themselves included —
there is no owner or admin check. `200` returns the task as `TaskRead`, with
its tags and the new assignee. An unknown task is `404` (`task-not-found`); an
unknown assignee is `422` (`assignee-not-found`); a disabled one is `422`
(`assignee-inactive`). If a user is deleted while the assign is in flight, it is
`409` (`assignment-conflict`) and nothing is written — a retry then gets the
precise answer. `assignee_id` is required and cannot be `null`, so
there is no unassign. Assigning the user the task already has is a `200`
no-op that writes no history — checked before the assignee is looked up, so
it stays `200` even if that user has since been disabled. Each real change
inserts a `task_assignment` row (new assignee, who did it);
there is no endpoint to read that history, only SQL. The task row is locked for
the duration so two concurrent assigns to the same user record one change,
not two — see `docs/database.md`.

Known inconsistency: `POST /projects/{project_id}/tasks` still accepts a
disabled user as `assignee_id`, while assign refuses one.

```bash
curl -s -X POST localhost:8000/api/v1/tasks/1/comments -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"content": "Looks good"}'
```

`201` returns `{id, task_id, author, content, created_at, updated_at}` with
`author` as the caller. `content` is trimmed and must be 1 to 5,000
characters afterwards, so a blank one is `422`. The author comes from the
token and the task from the path; an `author_id` in the body is ignored. An
unknown task is `404` (`task-not-found`). `author` becomes `null` if the
author's account is later removed; the comment stays.

```bash
curl -s -X DELETE localhost:8000/api/v1/tasks/1/comments/1 -H "Authorization: Bearer $TOKEN"
```

`204` with no body, and no undo. The checks run in this order: `401` for a
missing or bad token, `403` (`inactive-user`) for a disabled account, `404`
(`task-not-found`), `404` (`comment-not-found`, also when the comment exists
but belongs to another task), then `403` (`comment-forbidden`) unless the
caller is the comment's author, an admin or the owner of the task's project.
No endpoint sets `project.owner_id`, so through the API only an admin or the
author passes. A delete that loses a race with another delete is also a
`comment-not-found`.

## Email notifications

A new comment emails the task's assignee, and nobody else. Nothing is sent
when the task has no assignee, when the assignee is the comment's author, when
the assignee is disabled, or when the assignee has no email address. The
mail is plain text: who commented, the task's id and title, and the comment.

It is sent after the comment is saved and after the response goes out, by
FastAPI `BackgroundTasks` — no queue and no retry, so a message is lost if the
process dies first. A failure (mail server down, refused, timed out) is logged
with the task and comment ids and never reaches the client; the comment is
already saved either way. The recipient's address is not logged. At startup
one log line says whether mail is on.

With no `SMTP_HOST` the app runs and sends nothing. Mailpit, in
`docker-compose.yml`, accepts anything and delivers nothing — for local use
only. Settings:

| Variable | Default | |
|---|---|---|
| `SMTP_HOST` | unset | Unset disables email. |
| `SMTP_PORT` | `1025` | |
| `SMTP_USERNAME` | unset | Authenticate only when set. |
| `SMTP_PASSWORD` | unset | e.g. `SMTP_PASSWORD=<your-password>`. |
| `SMTP_USE_TLS` | `false` | `true` is implicit TLS; otherwise STARTTLS is used when the server offers it. |
| `SMTP_TIMEOUT` | `10` | Seconds to wait on the server. |
| `MAIL_FROM` | `TaskHub <noreply@taskhub.local>` | |

## Tag cache

`GET /tags` is served from Redis when it can be, from Postgres when it cannot,
and the response is byte for byte the same either way. Each page is stored
under `tags:v{version}:p{page}:s{size}` for 300 seconds. `POST`, `PATCH` and
`DELETE /tags` run `INCR tags:version` once their commit has succeeded, which
orphans every stored page at once; a refused write (404, 409, 422) changes
nothing. An empty page is never stored: `page` and `size` come from an
unauthenticated query string, and caching them would let a client mint a key
per combination. `GET /tags/{id}` is not cached.

The cache fails open. A Redis that is down or slow (0.5 s timeouts, no
retries) is logged at WARNING and skipped: reads go to Postgres and writes
still succeed. The one cost is that a write whose `INCR` failed can leave the
list stale until the TTL runs out. Run Redis with `maxmemory-policy noeviction`
(or no `maxmemory`): if `tags:version` alone is evicted it resets to 0 and old
v0 pages can be served for up to one TTL.

To run without it, leave `REDIS_URL` unset — no connection is ever attempted.
The compose Redis has no password and is for local development only; in
production supply your own `REDIS_URL`.

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

The brief names FastAPI's `TestClient`; the suite uses `httpx.AsyncClient`
over `ASGITransport` (the `api_client` fixture) instead. The app is async on
asyncpg, and that client runs the app on a loop of its own, which cannot share
the test's connection and its rolled-back transaction — FastAPI's "Async
Tests" guide takes the same route. The Register → Create Task flow is
`tests/test_register_and_create_task_flow.py`.

The tag cache tests use a real Redis (`docker compose up -d redis`). They run
against db 15 of the Redis in `REDIS_URL`, emptying it around each test, or
against `TEST_REDIS_URL` when that is set; with neither set they fail naming
both. They refuse to run on the database `REDIS_URL` itself points at. The
suite otherwise ignores `REDIS_URL` from `.env`.

Mail tests need no Mailpit: they override the `Mailer` with a recording one,
and send through `SmtpMailer` to an in-process `aiosmtpd` server. The suite
ignores `SMTP_HOST` from `.env`.

Two suites are the exception and commit for real, because a rolled-back
transaction cannot show a missing `commit()` or hold two competing
transactions: `tests/test_service_commits.py` and
`tests/test_task_assign_concurrency.py`. Their `committing_sessions` fixture
(`tests/conftest.py`) empties the tables before each test as well as after, so
a killed run cannot poison the next one.
