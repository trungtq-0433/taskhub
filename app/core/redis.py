"""The Redis client behind the tag cache.

Redis is optional: with no `REDIS_URL`, `get_redis_client()` returns `None` and
nothing here ever connects. The client is built on first use rather than in
`lifespan` because a Redis client belongs to the event loop it first ran on,
and `lifespan` does not run under the test transport. `lifespan` closes it.
"""

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.core.config import settings

# A dead Redis must cost a request about half a second, not a hang.
SOCKET_TIMEOUT_SECONDS = 0.5

_client: Redis | None = None


def make_client(url: str) -> Redis:
    """A client with short timeouts, strings in and out, and no retries.

    redis-py retries a failed command three times with exponential backoff by
    default, which turns one dead-Redis call into seconds; the cache would
    rather fail fast and let the caller fall back to Postgres. Building the
    client opens no connection.
    """
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
    )


def get_redis_client() -> Redis | None:
    """The shared client, or `None` when `REDIS_URL` is unset."""
    global _client
    if settings.redis_url is None:
        return None
    if _client is None:
        _client = make_client(settings.redis_url)
    return _client


async def close_redis_client() -> None:
    """Close the client if one was ever built; the next call builds a new one."""
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()
