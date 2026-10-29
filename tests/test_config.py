"""Settings resolution and the guards that stop a misconfigured boot."""

import re
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


def test_smtp_is_optional_and_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # `_settings` ignores .env but not the process environment.
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_USE_TLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SMTP_TIMEOUT", raising=False)
    monkeypatch.delenv("MAIL_FROM", raising=False)

    cfg = _settings()

    assert cfg.smtp_host is None
    assert cfg.smtp_port == 1025
    assert cfg.smtp_username is None
    assert cfg.smtp_password is None
    assert cfg.smtp_use_tls is False
    assert cfg.smtp_timeout == 10
    assert cfg.mail_from == "TaskHub <noreply@taskhub.local>"


@pytest.mark.parametrize("port", [0, 65536])
def test_an_smtp_port_outside_1_65535_is_refused(port: int) -> None:
    with pytest.raises(ValidationError, match="smtp_port"):
        _settings(smtp_port=port)


def test_the_smtp_password_never_shows_in_repr() -> None:
    cfg = _settings(smtp_password="hunter2-secret")

    assert "hunter2-secret" not in repr(cfg)
    assert cfg.smtp_password is not None
    assert cfg.smtp_password.get_secret_value() == "hunter2-secret"


def test_redis_is_optional_and_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("REDIS_URL", "REDIS_TIMEOUT", "TAG_CACHE_TTL"):
        monkeypatch.delenv(name, raising=False)

    cfg = _settings()

    assert cfg.redis_url is None
    assert cfg.redis_timeout == 0.5
    assert cfg.tag_cache_ttl == 300


def test_cors_origins_are_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset allows no browser origin at all, so a forgotten value fails closed."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert _settings().cors_origins == []


def test_cors_origins_are_read_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the env source, which on its own would demand JSON for a list."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://app.example.com")

    assert _settings().cors_origins == ["http://localhost:3000", "https://app.example.com"]


def test_a_wildcard_cors_origin_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match=r"CORS_ORIGINS must not contain \*"):
        _settings(environment="production", cors_origins="*")

    # ...and is fine anywhere else.
    assert _settings(environment="local", cors_origins="*").cors_origins == ["*"]


@pytest.mark.parametrize(
    "entry",
    [
        "http://localhost:3000/",
        "localhost:3000",
        '["http://localhost:3000"]',
        "http://localhost:3000/app",
    ],
)
def test_a_cors_origin_that_is_not_an_origin_is_refused(entry: str) -> None:
    """CORS compares `Origin` exactly, so a near-miss would silently match nothing."""
    with pytest.raises(ValidationError, match=re.escape(f"CORS_ORIGINS entry {entry!r}")):
        _settings(cors_origins=entry)


def test_log_level_is_unset_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset keeps the DEBUG-follows-`debug` rule, which only `None` can express."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert _settings().log_level is None


def test_an_unknown_log_level_is_refused() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        _settings(log_level="LOUD")
