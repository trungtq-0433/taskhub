"""Settings resolution and the guards that stop a misconfigured boot."""

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# A Settings() built in a test would otherwise pick up the developer's own
# .env; these tests supply every value explicitly instead.
COMPLETE = {"environment": "local", "postgres_password": "secret"}


def _settings(**overrides: object) -> Settings:
    """Build settings from explicit values, ignoring any .env on disk."""
    return Settings(_env_file=None, **{**COMPLETE, **overrides})  # type: ignore[arg-type]


def test_app_version_matches_pyproject() -> None:
    """The version is stated twice; this is what stops the two from drifting."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert settings.app_version == pyproject["project"]["version"]


@pytest.mark.parametrize("missing", ["environment", "postgres_password"])
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


def test_database_url_escapes_special_characters_in_the_password() -> None:
    """A password with `@` or `/` must not corrupt the host part of the DSN."""
    dsn = _settings(postgres_password="p@ss/w#rd", postgres_host="db.internal").database_url

    assert "@db.internal" in dsn
    assert "p%40ss%2Fw%23rd" in dsn


def test_database_url_override_wins_over_the_parts() -> None:
    managed = "postgresql+asyncpg://u:p@managed.example:5432/prod"

    assert _settings(DATABASE_URL=managed).database_url == managed
