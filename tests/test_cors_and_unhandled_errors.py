"""CORS, and what a browser on another origin sees when the app fails.

Each test builds its own app: what is checked is how `create_app()` stacks the
middleware around the routes. The origin list and `debug` are patched for the
whole request, never left to a developer's `.env`.

The transport keeps its default `raise_app_exceptions=True`, so an exception
that escapes the app fails the test instead of turning into a quiet 500.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

import pytest
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import create_app
from app.schemas.problem import PROBLEM_MEDIA_TYPE

ALLOWED = "http://localhost:3000"
ALLOW_ORIGIN = "access-control-allow-origin"

# (origins configured, origin the request comes from): the two ways to be refused.
NOT_ALLOWED = pytest.mark.parametrize(
    ("origins", "origin"),
    [([ALLOWED], "http://evil.example"), ([], ALLOWED)],
    ids=["unlisted-origin", "nothing-configured"],
)


async def _ok() -> dict[str, str]:
    return {"status": "ok"}


async def _boom() -> None:
    raise RuntimeError("secret-ish")


async def _stream() -> StreamingResponse:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"first chunk"
        raise RuntimeError("after the headers went out")

    return StreamingResponse(chunks())


@asynccontextmanager
async def _client(origins: list[str], *, debug: bool = False) -> AsyncIterator[AsyncClient]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "cors_origins", origins)
        patch.setattr(settings, "debug", debug)
        app = create_app()
        for path, endpoint in [
            ("/_test/ok", _ok),
            ("/_test/boom", _boom),
            ("/_test/stream", _stream),
        ]:
            app.router.add_api_route(path, endpoint, methods=["GET"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


def _preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "Authorization, Content-Type",
    }


async def test_a_preflight_from_an_allowed_origin_is_answered() -> None:
    async with _client([ALLOWED]) as client:
        response = await client.options("/_test/ok", headers=_preflight(ALLOWED))

    assert response.status_code == HTTPStatus.OK
    assert response.headers[ALLOW_ORIGIN] == ALLOWED
    assert "PATCH" in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert response.headers["x-request-id"]


@NOT_ALLOWED
async def test_a_preflight_from_any_other_origin_is_refused(
    origins: list[str], origin: str
) -> None:
    """CORSMiddleware's own plain-text 400: the one answer that is not a problem.

    A browser never shows a preflight body to script, only its headers.
    """
    async with _client(origins) as client:
        response = await client.options("/_test/ok", headers=_preflight(origin))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.headers["content-type"].startswith("text/plain")
    assert ALLOW_ORIGIN not in response.headers


async def test_an_allowed_origin_can_read_the_response_and_its_request_id() -> None:
    async with _client([ALLOWED]) as client:
        response = await client.get("/_test/ok", headers={"Origin": ALLOWED})

    assert response.status_code == HTTPStatus.OK
    assert response.headers[ALLOW_ORIGIN] == ALLOWED
    # The answer differs per origin, so a shared cache must key on it.
    assert "origin" in response.headers["vary"].lower()
    exposed = response.headers["access-control-expose-headers"].lower().split(",")
    assert "x-request-id" in [name.strip() for name in exposed]


@NOT_ALLOWED
async def test_any_other_origin_gets_no_allow_origin_header(
    origins: list[str], origin: str
) -> None:
    """Still served: CORS is enforced by the browser, which then withholds the body."""
    async with _client(origins) as client:
        response = await client.get("/_test/ok", headers={"Origin": origin})

    assert response.status_code == HTTPStatus.OK
    assert ALLOW_ORIGIN not in response.headers


async def test_an_unhandled_error_keeps_cors_and_the_request_id_and_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rendered inside CORS and the request id, not in ServerErrorMiddleware outside both.

    Without that, the browser hides the 500 from the frontend for want of
    `Access-Control-Allow-Origin`, and the id the user would quote is missing.
    """
    with caplog.at_level(logging.ERROR):
        async with _client([ALLOWED]) as client:
            response = await client.get("/_test/boom", headers={"Origin": ALLOWED})

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.headers[ALLOW_ORIGIN] == ALLOWED
    problem = response.json()
    assert problem["request_id"] == response.headers["x-request-id"]
    assert "secret-ish" not in problem["detail"]

    (record,) = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert record.name == "app.core.handlers"
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


async def test_under_debug_the_detail_is_the_exception_text() -> None:
    """The cause as JSON — Starlette's HTML traceback page never gets the chance."""
    async with _client([ALLOWED], debug=True) as client:
        response = await client.get("/_test/boom")

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["detail"] == "secret-ish"


async def test_an_error_after_the_response_started_is_re_raised() -> None:
    """The status line is already out, so no problem document can follow it.

    Swallowing the error would leave a truncated body and nothing in the log;
    re-raised, the server logs it and drops the connection.
    """
    async with _client([ALLOWED]) as client:
        with pytest.raises(RuntimeError, match="after the headers went out"):
            await client.get("/_test/stream")
