"""Application settings.

Values are resolved per field, in this order:

    1. a real environment variable   (production: SSM, K8s secrets, compose)
    2. a line in `.env`              (local development)
    3. the default written below     (when neither exists)

Fields with no default are **required**: if nothing supplies them the process
fails to start with a message naming the missing variable, rather than running
on a guess. That is deliberate for anything environment-specific or secret.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    """Typed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Field `app_name` matches APP_NAME. With case sensitivity on, the
        # variable would have to be spelled `app_name`, against every shell
        # convention there is.
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    # Identical in every environment, so these are not worth an .env entry.
    app_name: str = "TaskHub API"
    app_version: str = "0.1.0"  # kept in step with pyproject.toml by a test
    api_prefix: str = "/api/v1"

    # Required: the one thing that tells local apart from staging apart from
    # production. Guessing it wrong is how a deployment ends up in debug mode.
    environment: Literal["local", "test", "staging", "production"]
    debug: bool = False

    # --- Database --------------------------------------------------------
    # One URL, not five parts. Production hands this out at provision time
    # (RDS, Neon, Supabase, a Terraform output); compose supplies it for local.
    database_url: str = Field(
        alias="DATABASE_URL",
        description="Async Postgres DSN, e.g. postgresql+asyncpg://user:pass@host:5432/db",
    )

    # SQLAlchemy engine tuning — sensible defaults, raise them under load.
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_pre_ping: bool = True
    db_pool_recycle: int = 1800

    # --- Auth --------------------------------------------------------------
    # Required, like DATABASE_URL: a guessed or default signing key is a
    # forgeable token waiting to happen. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    # 32 bytes is the floor for an HS256 key; token_urlsafe(48) clears it with
    # room to spare. The algorithm itself is not a setting — see
    # `app.core.security.JWT_ALGORITHM` — making it configurable only invites
    # a `none`/RS256 downgrade mix-up.
    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY", min_length=32)
    access_token_expire_minutes: int = Field(default=30, ge=1)

    @field_validator("database_url", mode="after")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """Accept the DSN a provider gives you, and make it usable with asyncpg.

        Managed Postgres hands out `postgres://` or `postgresql://`, both of
        which resolve to the *synchronous* driver and fail inside an async
        engine with an error that says nothing about the cause. The two
        well-known synchronous schemes are upgraded; anything else is refused
        here rather than at the first query.
        """
        try:
            url = make_url(value)
        except ArgumentError as exc:
            raise ValueError(f"DATABASE_URL is not a valid database URL: {exc}") from exc

        if url.drivername in ("postgres", "postgresql"):
            url = url.set(drivername="postgresql+asyncpg")
        elif url.drivername != "postgresql+asyncpg":
            raise ValueError(
                f"DATABASE_URL must use the postgresql+asyncpg driver, got {url.drivername!r}."
            )

        return url.render_as_string(hide_password=False)

    @model_validator(mode="after")
    def _refuse_debug_in_production(self) -> Self:
        """Debug mode in production leaks tracebacks — fail at boot instead."""
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be false when ENVIRONMENT is production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — safe to use as a FastAPI dependency."""
    return Settings()


settings = get_settings()
