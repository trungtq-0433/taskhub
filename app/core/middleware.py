"""Request-scoped correlation id.

Every response carries `X-Request-ID`, and every error envelope repeats it in
its body. That one value is what ties a user's screenshot to a log line, so it
is assigned here — as early as possible — rather than inside a handler.

Written as raw ASGI rather than `BaseHTTPMiddleware`: the latter buffers
responses and breaks streaming, which is a steep price for setting one header.
"""

from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"

# Readable from anywhere, including exception handlers that never see the Request.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id(request: Request | None = None) -> str | None:
    """Correlation id of the request being served, if there is one.

    Prefers the value stored on the ASGI scope. Starlette runs its server-error
    handler *outside* this middleware, by which point the context variable has
    already been reset — and a 500 is exactly when the id matters most. The
    scope survives that unwinding; the context variable does not.
    """
    if request is not None:
        stored = request.scope.get("state", {}).get("request_id")
        if stored:
            return str(stored)
    return request_id_ctx.get()


class RequestIDMiddleware:
    """Honour an inbound `X-Request-ID`, or mint one, and echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1").lower(): value for key, value in scope["headers"]}
        inbound = headers.get(REQUEST_ID_HEADER)
        request_id = inbound.decode("latin-1")[:128] if inbound else uuid4().hex

        token = request_id_ctx.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_ctx.reset(token)
