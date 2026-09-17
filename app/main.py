"""FastAPI application factory and ASGI entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.handlers import DEFAULT_ERROR_RESPONSES, register_exception_handlers
from app.core.middleware import RequestIDMiddleware

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s (%s)", settings.app_name, settings.environment)
    yield
    await dispose_engine()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        responses=DEFAULT_ERROR_RESPONSES,
    )

    # Outermost middleware: the correlation id must exist before anything
    # downstream can fail and try to report it.
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
