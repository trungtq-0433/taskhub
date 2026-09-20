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

The variable name comes from the field name: `db_pool_size` matches
`DB_POOL_SIZE`. `case_sensitive=False` is what allows the conventional uppercase
spelling — turn it on and `.env` would have to say `db_pool_size`.

A production host usually has **no `.env` file at all**. The secret store injects
tier 1 and the same image runs unchanged.

## Required variables

A field with no default is required. Miss one and the process refuses to start,
before it binds a port:

```
pydantic_core.ValidationError: 1 validation error for Settings
DATABASE_URL
  Field required [type=missing]
```

A missing database URL should stop a deploy, not produce a service that fails on
its first query.

| Variable | Why it is required |
|---|---|
| `ENVIRONMENT` | `local` / `test` / `staging` / `production`. Guessing it is how a deploy ends up in debug mode. A value outside the four is rejected. |
| `DATABASE_URL` | The whole database connection, as one URL. A default would point somewhere. |

`ENVIRONMENT=production` together with `DEBUG=true` is also refused at boot:
debug mode makes Starlette answer unhandled exceptions with an HTML traceback
instead of a problem document.

Everything else has a default that is correct in every environment, so `.env`
only carries what actually differs.

## The database is one URL

The application takes `DATABASE_URL` and nothing else about the database, which
matches how every environment works: the database is provisioned first — by
Terraform, by a managed provider, by `docker-compose.yml` locally — and hands out
a connection string. The dev container's own credentials therefore live in the
compose file, not in `.env`.

Managed Postgres hands out `postgres://` or `postgresql://`. Both resolve to the
*synchronous* driver, which fails inside an async engine with an error that names
nothing useful, so they are upgraded at boot:

```
postgres://…            →  postgresql+asyncpg://…     upgraded
postgresql://…          →  postgresql+asyncpg://…     upgraded
postgresql+psycopg2://… →  refused at boot
not a url               →  refused at boot
```

Percent-encoded credentials survive the rewrite, which matters for generated
passwords containing `@` or `/`.

## What does not belong in `.env`

`APP_NAME`, `APP_VERSION` and `API_PREFIX` are identical in every environment, so
they stay in `config.py`. Listing them would suggest a deploy has to decide them —
and changing `API_PREFIX` is a breaking change, not a knob.

`APP_VERSION` is stated in both `config.py` and `pyproject.toml`. A test asserts
the two match, so bumping one without the other fails the suite rather than
letting the application report a version the build does not have.
