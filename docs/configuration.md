# Configuration

Settings live in `app/core/config.py` as a typed `Settings` model. Nothing reads
`os.environ` directly.

## How a value is resolved

Per field, in this order — the first hit wins:

| | Source | Used by |
|---|---|---|
| 1 | a real environment variable | production: SSM, K8s secrets, docker compose |
| 2 | a line in `.env` | local development |
| 3 | the default in `config.py` | when neither exists |

Field `postgres_host` matches `POSTGRES_HOST`; the mapping comes from the field
name. `case_sensitive=False` is what allows the conventional uppercase spelling —
turn it on and `.env` would have to say `postgres_host`.

A production host usually has **no `.env` file at all**. The secret store injects
tier 1 and the same image runs unchanged.

## Required variables

A field with no default is required. Miss one and the process refuses to start:

```
pydantic_core.ValidationError: 1 validation error for Settings
postgres_password
  Field required [type=missing]
```

That is the intent — a missing database password should stop a deploy, not
produce a service that fails on its first query.

| Variable | Why it is required |
|---|---|
| `ENVIRONMENT` | `local` / `test` / `staging` / `production`. Guessing it is how a deploy ends up in debug mode. A value outside the four is rejected. |
| `POSTGRES_PASSWORD` | A secret must never carry a default. |

Everything else has a default that is correct in every environment, so `.env`
only needs to carry what actually differs.

## Guards that run at boot

- `ENVIRONMENT` outside the four allowed values → refused.
- `ENVIRONMENT=production` together with `DEBUG=true` → refused. Debug mode makes
  Starlette answer unhandled exceptions with an HTML traceback instead of a
  problem document, which leaks source paths.

Both fail during `Settings()`, which runs at import time — so the container exits
immediately rather than serving traffic in a bad state.

## Database URL

`database_url` is assembled by SQLAlchemy's `URL.create`, which percent-encodes
the credentials. This matters: neither string concatenation nor pydantic's
`PostgresDsn.build` escapes them, and a password containing `@` or `/` then
produces a DSN pointing at a different host.

```
password p@ss/w#rd
  PostgresDsn.build →  postgresql+asyncpg://taskhub:p@ss/w#rd@db.internal:5432/taskhub   ✗
  URL.create        →  postgresql+asyncpg://taskhub:p%40ss%2Fw%23rd@db.internal:5432/taskhub   ✓
```

Setting `DATABASE_URL` overrides the whole thing, which is what managed providers
(RDS, Neon, Supabase) hand out.

## What does not belong in `.env`

`APP_NAME`, `APP_VERSION` and `API_PREFIX` are identical in every environment, so
they stay in `config.py`. Listing them in `.env.example` would suggest a deploy
has to decide them — and changing `API_PREFIX` is a breaking change, not a knob.

`APP_VERSION` is stated in both `config.py` and `pyproject.toml`. A test asserts
the two match, so bumping one without the other fails the suite rather than
making `/health` report a version the build does not have.
