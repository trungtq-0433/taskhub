"""Settings resolution and the guards that stop a misconfigured boot."""

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings, settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# A Settings() built in a test would otherwise pick up the developer's own
# .env; these tests supply every value explicitly instead.
COMPLETE = {
    "environment": "local",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/taskhub",
    "JWT_SECRET_KEY": "a" * 32,
}


def _settings(**overrides: object) -> Settings:
    """Build settings from explicit values, ignoring any .env on disk."""
    return Settings(_env_file=None, **{**COMPLETE, **overrides})  # type: ignore[arg-type]


def test_app_version_matches_pyproject() -> None:
    """The version is stated twice; this is what stops the two from drifting."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert settings.app_version == pyproject["project"]["version"]


@pytest.mark.parametrize("missing", ["environment", "DATABASE_URL", "JWT_SECRET_KEY"])
def test_required_variable_missing_fails_the_boot(missing: str) -> None:
    """Omitting a required variable must fail loudly, naming the variable."""
    values = {key: value for key, value in COMPLETE.items() if key != missing}

    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **values)  # type: ignore[arg-type]

    assert missing.upper() in str(caught.value).upper()


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="prod")  # the value is `production`


def test_debug_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="DEBUG must be false"):
        _settings(environment="production", debug=True)

    # ...and is fine anywhere else.
    assert _settings(environment="staging", debug=True).debug


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_synchronous_scheme_is_upgraded_to_asyncpg(scheme: str) -> None:
    """Managed providers hand out sync schemes; the async engine cannot use them."""
    dsn = _settings(DATABASE_URL=f"{scheme}://u:p@managed.example:5432/prod").database_url

    assert dsn.startswith("postgresql+asyncpg://")
    assert "@managed.example:5432/prod" in dsn


def test_a_driver_we_cannot_run_is_refused_at_boot() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg driver"):
        _settings(DATABASE_URL="postgresql+psycopg2://u:p@host:5432/db")


def test_an_unparseable_url_is_refused_at_boot() -> None:
    with pytest.raises(ValidationError, match="not a valid database URL"):
        _settings(DATABASE_URL="this is not a url")


def test_jwt_secret_key_below_minimum_length_is_rejected() -> None:
    """32 bytes is the floor for an HS256 signing key; anything shorter is refused."""
    with pytest.raises(ValidationError, match=r"(?i)jwt_secret_key"):
        _settings(JWT_SECRET_KEY="a" * 31)


def test_access_token_expiry_defaults_to_thirty_minutes() -> None:
    assert _settings().access_token_expire_minutes == 30


def test_access_token_expiry_must_be_at_least_one_minute() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        _settings(ACCESS_TOKEN_EXPIRE_MINUTES=0)


def test_password_special_characters_survive_normalisation() -> None:
    """Percent-encoding in the supplied DSN must not be mangled on the way through."""
    dsn = _settings(
        DATABASE_URL="postgresql://u:p%40ss%2Fw%23rd@db.internal:5432/taskhub"
    ).database_url

    assert "@db.internal" in dsn
    assert make_url(dsn).password == "p@ss/w#rd"
