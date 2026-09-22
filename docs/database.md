# Database and Migrations

How a model change turns into a migration, and the one thing every new entity
must inherit.

## Adding or changing a model

1. Write or edit the model in `app/models/`. Inherit `TimestampMixin` (see
   below) unless the entity genuinely has no `created_at`/`updated_at`.
2. Generate the migration:

   ```bash
   uv run alembic revision --autogenerate -m "add task table"
   ```

3. Lint the generated file. Alembic can do this automatically via
   `post_write_hooks` in `alembic.ini`, but that section ships commented out
   in this project, so run it by hand for now:

   ```bash
   uv run ruff check --fix migrations/versions/<new_revision>.py
   ```

4. Confirm the diff is complete — autogenerate again with a throwaway
   message:

   ```bash
   uv run alembic revision --autogenerate -m check
   ```

   An empty `upgrade()`/`downgrade()` means the real migration from step 2
   already captured the full model change; delete this throwaway file. Any
   operations still showing up mean something was missed the first time —
   fold them into the real migration instead of keeping two files.
5. Apply it: `uv run alembic upgrade head`.

Alembic resolves `DATABASE_URL` from `app.core.config.settings` rather than
`alembic.ini`, and runs on its own async engine rather than the app's pool —
see the module docstring in `migrations/env.py` for why.

## The timestamp mixin

Every entity inherits `TimestampMixin` (`app/models/mixins.py`) for
`created_at`/`updated_at`. It sets `eager_defaults=True` on the mapper, which
is load-bearing under async SQLAlchemy: without it, reading either column
right after a write triggers a lazy refresh — I/O in a context async
forbids — and raises `MissingGreenlet` instead. `expire_on_commit=False` does
not substitute for it, since the attribute is expired at flush, not commit.
The mixin's docstring has the full reasoning if you're deciding whether a new
model needs it.
