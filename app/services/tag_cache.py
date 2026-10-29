"""Redis cache for one page of the tag list.

Fail open: the cache may speed `GET /tags` up and must never be the reason it,
or a tag write, fails. Every Redis error is logged at WARNING and the caller
carries on as if there were no cache.

Invalidation is a version number, not a key hunt. A page lives under
`tags:v{version}:p{page}:s{size}`; a write bumps `tags:version` *after* its
commit, so every earlier page is orphaned at once and left to expire. A reader
that raced the writer and stored pre-commit data stored it under the old
version, which nobody asks for after the bump.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.redis import get_redis_client
from app.schemas.base import Page
from app.schemas.tag import TagRead

logger = logging.getLogger(__name__)

# `OSError` and `TimeoutError` are not `RedisError`s: a refused or timed-out
# connection surfaces as one of the two depending on where it fails.
REDIS_DOWN = (RedisError, OSError, TimeoutError)
VERSION_KEY = "tags:version"
TTL_SECONDS = 300


class TagListCache:
    def __init__(self, client: Redis) -> None:
        self.client = client

    async def get_or_load(
        self, page: int, size: int, load: Callable[[], Awaitable[Page[TagRead]]]
    ) -> Page[TagRead]:
        """The cached page, or `load()`'s result, stored for next time.

        `load()` stays outside every `try`: asyncpg raises `OSError` when
        Postgres is down, and that must reach the 503 handler rather than be
        mistaken for a Redis outage. Once a Redis call fails the request stops
        using Redis, so one outage logs once, not three times.
        """
        try:
            # redis-py's stubs type replies as bytes; `make_client` decodes them.
            version = str(await self.client.get(VERSION_KEY) or "0")
            key = f"tags:v{version}:p{page}:s{size}"
            cached = await self.client.get(key)
        except REDIS_DOWN as exc:
            self._warn(exc)
            return await load()

        if cached:
            try:
                return Page[TagRead].model_validate_json(cached)
            except ValidationError:
                pass  # an older deploy's shape: a miss

        loaded = await load()
        if not loaded.items:
            # `page` and `size` come from an unauthenticated query string: storing
            # empty pages would let a client mint a key per combination.
            return loaded
        try:
            await self.client.set(key, loaded.model_dump_json(), ex=TTL_SECONDS)
        except REDIS_DOWN as exc:
            self._warn(exc)
        return loaded

    async def invalidate(self) -> None:
        """Orphan every cached page. Call only after the write has committed."""
        try:
            await self.client.incr(VERSION_KEY)
        except REDIS_DOWN as exc:
            self._warn(exc)

    @staticmethod
    def _warn(exc: Exception) -> None:
        # The exception, never the URL: it may carry a password.
        logger.warning("Tag cache unavailable (%s); continuing without it", exc)


async def get_tag_list_cache() -> TagListCache | None:
    """The cache, or `None` when Redis is not configured."""
    client = get_redis_client()
    return None if client is None else TagListCache(client)


TagListCacheDep = Annotated[TagListCache | None, Depends(get_tag_list_cache)]
