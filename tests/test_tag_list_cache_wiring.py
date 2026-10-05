"""How the tag cache gets (or does not get) a Redis client. Needs no Redis."""

import pytest

from app.core import redis as redis_module
from app.core.config import settings
from app.core.redis import close_redis_client, get_redis_client
from app.services.tag_cache import get_tag_list_cache


async def test_no_cache_without_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset `REDIS_URL` means no client is even built, let alone connected."""

    def refuse(url: str) -> object:
        raise AssertionError("a Redis client was built although REDIS_URL is unset")

    monkeypatch.setattr(settings, "redis_url", None)
    monkeypatch.setattr(redis_module, "make_client", refuse)

    assert get_redis_client() is None
    assert await get_tag_list_cache() is None


async def test_the_client_is_created_once_and_forgotten_on_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building a client opens no connection, so a URL nothing listens on is safe.
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    try:
        first = get_redis_client()
        assert first is not None
        assert get_redis_client() is first

        await close_redis_client()

        second = get_redis_client()
        assert second is not None
        assert second is not first
    finally:
        await close_redis_client()
