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

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


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
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "taskhub"
    postgres_password: str  # required: a secret must never have a default
    postgres_db: str = "taskhub"

    # SQLAlchemy engine tuning — sensible defaults, raise them under load.
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_pre_ping: bool = True
    db_pool_recycle: int = 1800

    # Managed databases hand out one ready-made DSN instead of the parts above.
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async DSN used by the SQLAlchemy engine.

        Assembled with SQLAlchemy's own `URL.create`, which percent-encodes the
        credentials. Neither string concatenation nor `PostgresDsn.build` does:
        a password containing `@` or `/` would silently produce a DSN aimed at
        a different host entirely.
        """
        if self.database_url_override:
            return self.database_url_override
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

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
