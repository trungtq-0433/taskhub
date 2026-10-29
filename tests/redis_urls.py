"""Where the cache tests find their Redis (decision 16): never a hard-coded port."""

import os
from urllib.parse import urlsplit

import pytest

from app.core.config import settings

TEST_DB_INDEX = 15

# Read now: the session fixture in conftest blanks `settings.redis_url`.
DEV_REDIS_URL = settings.redis_url


def database_of(url: str) -> str:
    """`host:port/db`, with the db index defaulted the way Redis defaults it."""
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port or 6379}/{parts.path.lstrip('/') or '0'}"


def redis_url_for_tests() -> str:
    """`TEST_REDIS_URL`, else the dev `REDIS_URL` moved to db 15, else fail.

    Not named `test_*` (pytest would collect it). The dev URL's host and port
    are reused so a machine that remaps Redis needs no second setting.
    """
    override = os.environ.get("TEST_REDIS_URL")
    if override:
        return override
    if DEV_REDIS_URL:
        return urlsplit(DEV_REDIS_URL)._replace(path=f"/{TEST_DB_INDEX}").geturl()
    pytest.fail(
        "The tag cache tests need a Redis: set TEST_REDIS_URL, or REDIS_URL "
        "(its db index is replaced by 15). `docker compose up -d redis` starts one.",
        pytrace=False,
    )
