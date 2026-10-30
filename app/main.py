"""FastAPI application factory and ASGI entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routers import health
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.handlers import (
    DEFAULT_ERROR_RESPONSES,
    register_exception_handlers,
    unhandled_exception_handler,
)
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    UnhandledExceptionMiddleware,
)
from app.core.redis import close_redis_client

configure_logging()
logger = logging.getLogger(__name__)

# Only the origins are configuration. These are the verbs the routes use and the
# headers a client sends; `X-Request-ID` is exposed so a frontend can read it
# and quote it in a bug report. No credentials: auth is a bearer header, not cookies.
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
CORS_HEADERS = ["Authorization", "Content-Type", REQUEST_ID_HEADER]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s (%s)", settings.app_name, settings.environment)
    if settings.smtp_host is None:
        logger.info("Email notifications disabled: SMTP_HOST is not set")
    else:
        logger.info("Email notifications via %s:%d", settings.smtp_host, settings.smtp_port)
    yield
    await dispose_engine()
    await close_redis_client()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    # The interactive docs are unauthenticated: anyone who can reach the service
    # can read every route, payload shape and error code, and fire requests from
    # the page. That is exactly what you want while building and exactly what you
    # do not want facing the internet, so production serves none of the three.
    #
    # openapi_url has to go too. Leaving it while hiding /docs only removes the
    # UI — the schema it renders is still there for the asking.
    in_production = settings.environment == "production"

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if in_production else "/docs",
        redoc_url=None if in_production else "/redoc",
        openapi_url=None if in_production else "/openapi.json",
        responses=DEFAULT_ERROR_RESPONSES,
    )

    # Each add_middleware call wraps the ones before it, so the stack is built
    # innermost first. Outermost, the correlation id must exist before anything
    # downstream can fail and try to report it. CORS sits inside it, and the
    # catch-all inside CORS: an unhandled 500 then leaves through both, with the
    # headers a browser needs to read it, rather than from ServerErrorMiddleware
    # outside them (see UnhandledExceptionMiddleware).
    app.add_middleware(UnhandledExceptionMiddleware, handler=unhandled_exception_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=CORS_METHODS,
        allow_headers=CORS_HEADERS,
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(health.router)
    return app


app = create_app()
