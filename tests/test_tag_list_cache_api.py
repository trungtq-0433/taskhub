"""`GET /tags` through a real Redis, and what happens when there is none.

Redis is real, never a mock: the version-key scheme is only proven by Redis
actually holding and expiring keys. The URL comes from `TEST_REDIS_URL`, else
from the developer's `REDIS_URL` pointed at db 15 — see `redis_url_for_tests`.
"""

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import make_client
from app.main import app
from app.models import Tag
from app.services.tag_cache import VERSION_KEY, TagListCache, get_tag_list_cache
from tests.redis_urls import DEV_REDIS_URL, database_of, redis_url_for_tests
from tests.servers import free_port

BASE = "/api/v1/tags"


@pytest.fixture(scope="session")
async def _redis() -> AsyncGenerator[TagListCache, None]:
    """One live Redis for the run; a stopped one errors here, not in the fallback."""
    url = redis_url_for_tests()
    if DEV_REDIS_URL and database_of(url) == database_of(DEV_REDIS_URL):
        pytest.fail(
            "Refusing to FLUSHDB the development Redis database; "
            "set TEST_REDIS_URL to another one.",
            pytrace=False,
        )
    client = make_client(url)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.fail(f"Redis is not reachable for the cache tests ({exc}).", pytrace=False)
    yield TagListCache(client)
    await client.aclose()


@pytest.fixture
async def cache(_redis: TagListCache) -> AsyncGenerator[TagListCache, None]:
    """The test's cache, installed on the app, with the database emptied around it."""
    await _redis.client.flushdb()
    app.dependency_overrides[get_tag_list_cache] = lambda: _redis
    yield _redis
    app.dependency_overrides.pop(get_tag_list_cache, None)
    await _redis.client.flushdb()


async def _seed(db_session: AsyncSession, *names: str) -> None:
    db_session.add_all([Tag(name=name) for name in names])
    await db_session.flush()


async def _names(client: AsyncClient, **params: int) -> list[str]:
    response = await client.get(BASE, params=params)
    assert response.status_code == HTTPStatus.OK
    return [item["name"] for item in response.json()["items"]]


async def test_a_cached_page_is_byte_identical_to_an_uncached_one(
    api_client: AsyncClient, db_session: AsyncSession, cache: TagListCache
) -> None:
    await _seed(db_session, "alpha", "beta")

    app.dependency_overrides[get_tag_list_cache] = lambda: None
    uncached = await api_client.get(BASE)
    app.dependency_overrides[get_tag_list_cache] = lambda: cache
    miss = await api_client.get(BASE)
    hit = await api_client.get(BASE)

    assert await cache.client.exists("tags:v0:p1:s20") == 1, "the second read must be a hit"
    assert uncached.content == miss.content == hit.content


async def test_a_second_read_is_served_from_the_cache(
    api_client: AsyncClient, db_session: AsyncSession, cache: TagListCache
) -> None:
    await _seed(db_session, "alpha")
    assert await _names(api_client) == ["alpha"]

    await _seed(db_session, "beta")  # straight into Postgres: Redis does not know

    assert await _names(api_client) == ["alpha"]


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_a_write_bumps_the_version_and_the_next_read_is_fresh(
    method: str, api_client: AsyncClient, db_session: AsyncSession, cache: TagListCache
) -> None:
    await _seed(db_session, "alpha")
    first = await api_client.get(BASE)
    tag_id = first.json()["items"][0]["id"]
    assert await cache.client.get(VERSION_KEY) is None

    if method == "POST":
        response = await api_client.post(BASE, json={"name": "beta"})
        expected = ["alpha", "beta"]
    elif method == "PATCH":
        response = await api_client.patch(f"{BASE}/{tag_id}", json={"name": "omega"})
        expected = ["omega"]
    else:
        response = await api_client.delete(f"{BASE}/{tag_id}")
        expected = []
    assert response.is_success

    assert await cache.client.get(VERSION_KEY) == "1"
    assert await _names(api_client) == expected


@pytest.mark.parametrize(
    ("send", "status"),
    [
        (lambda c: c.post(BASE, json={"name": "alpha"}), HTTPStatus.CONFLICT),
        (lambda c: c.patch(f"{BASE}/999999", json={"name": "x"}), HTTPStatus.NOT_FOUND),
        (lambda c: c.delete(f"{BASE}/999999"), HTTPStatus.NOT_FOUND),
    ],
    ids=["duplicate-post", "missing-patch", "missing-delete"],
)
async def test_a_refused_write_does_not_bump_the_version(
    send: Callable[[AsyncClient], object],
    status: HTTPStatus,
    api_client: AsyncClient,
    db_session: AsyncSession,
    cache: TagListCache,
) -> None:
    await _seed(db_session, "alpha")
    await api_client.get(BASE)

    response = await send(api_client)  # type: ignore[misc]

    assert response.status_code == status
    assert await cache.client.get(VERSION_KEY) is None


async def test_the_key_names_version_page_and_size_and_expires_within_300_s(
    api_client: AsyncClient, db_session: AsyncSession, cache: TagListCache
) -> None:
    await _seed(db_session, "alpha")
    await api_client.get(BASE, params={"page": 1, "size": 5})

    assert await cache.client.keys("tags:*") == ["tags:v0:p1:s5"]
    assert 0 < await cache.client.ttl("tags:v0:p1:s5") <= 300


@asynccontextmanager
async def dead_redis(caplog: pytest.LogCaptureFixture) -> AsyncIterator[list[float]]:
    """Point the app at a closed port; yields `[elapsed]` once the block ends."""
    dead = TagListCache(make_client(f"redis://127.0.0.1:{free_port()}/0"))
    app.dependency_overrides[get_tag_list_cache] = lambda: dead
    elapsed: list[float] = []
    started = time.monotonic()
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.tag_cache"):
            yield elapsed
    finally:
        elapsed.append(time.monotonic() - started)
        app.dependency_overrides.pop(get_tag_list_cache, None)
        await dead.client.aclose()


async def test_an_unreachable_redis_falls_back_to_the_database_on_read(
    api_client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    await _seed(db_session, "alpha")

    async with dead_redis(caplog) as elapsed:
        names = await _names(api_client)

    assert names == ["alpha"]
    assert elapsed[0] < 2, "retries must be off: a dead Redis may cost 0.5 s, not seconds"
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


async def test_an_unreachable_redis_does_not_fail_a_write(
    api_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    async with dead_redis(caplog) as elapsed:
        response = await api_client.post(BASE, json={"name": "alpha"})

    assert response.status_code == HTTPStatus.CREATED
    assert elapsed[0] < 2
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


async def test_a_page_past_the_end_is_not_cached_but_a_real_page_is(
    api_client: AsyncClient, db_session: AsyncSession, cache: TagListCache
) -> None:
    await _seed(db_session, "alpha")

    assert await _names(api_client, page=99, size=5) == []
    assert await cache.client.keys("tags:v*:p*") == []

    assert await _names(api_client, page=1, size=5) == ["alpha"]
    assert await cache.client.keys("tags:v*:p*") == ["tags:v0:p1:s5"]
