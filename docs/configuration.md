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
DATABASE_URL
  Field required [type=missing]
```

That is the intent — a missing database URL should stop a deploy, not produce a
service that fails on its first query.

| Variable | Why it is required |
|---|---|
| `ENVIRONMENT` | `local` / `test` / `staging` / `production`. Guessing it is how a deploy ends up in debug mode. A value outside the four is rejected. |
| `DATABASE_URL` | The whole database connection, as one URL. No default, because a default would point somewhere. |

Everything else has a default that is correct in every environment, so `.env`
only carries what actually differs.

## The database is one URL, not five parts

The application takes `DATABASE_URL` and nothing else about the database. That
matches how every environment actually works: the database is provisioned first —
by Terraform, by a managed provider's console, by the compose file locally — and
it hands out a connection string.

Locally, the dev database's credentials belong to the container, so they are
written directly in `docker-compose.yml`. They are provisioning values for a
throwaway container, not application configuration, and giving them an `.env`
entry only invites someone to think the application cares.

```yaml
db:
  environment:
    POSTGRES_USER: taskhub        # this container's provisioning
    POSTGRES_PASSWORD: taskhub
    POSTGRES_DB: taskhub

api:
  environment:
    DATABASE_URL: postgresql+asyncpg://taskhub:taskhub@db:5432/taskhub
```

`POSTGRES_HOST_PORT` in `.env` is read by compose, not by the application — it
moves the host-side port binding when 5432 is already taken.

### The driver is normalised at boot

Managed Postgres hands out `postgres://` or `postgresql://`. Both resolve to the
*synchronous* driver, which fails inside an async engine with an error that says
nothing about the cause. Those two are upgraded to `postgresql+asyncpg://`
automatically; any other driver is refused at startup rather than at the first
query.

```
postgres://…            →  postgresql+asyncpg://…     upgraded
postgresql://…          →  postgresql+asyncpg://…     upgraded
postgresql+psycopg2://… →  refused at boot
not a url               →  refused at boot
```

Percent-encoded credentials survive the rewrite intact, which matters for
generated passwords containing `@` or `/`.

## What does not belong in `.env`

`APP_NAME`, `APP_VERSION` and `API_PREFIX` are identical in every environment, so
they stay in `config.py`. Listing them in `.env.example` would suggest a deploy
has to decide them — and changing `API_PREFIX` is a breaking change, not a knob.

`APP_VERSION` is stated in both `config.py` and `pyproject.toml`. A test asserts
the two match, so bumping one without the other fails the suite rather than
making `/health` report a version the build does not have.

Nor do the dev database's credentials: see above.
