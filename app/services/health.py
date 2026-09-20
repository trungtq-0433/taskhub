"""Readiness checks against the service's dependencies.

Also the smallest example of the shape every service follows: the class takes
its collaborators through `__init__`, and the module exports an `Annotated`
alias so routers depend on the service rather than on a database session.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionDep
from app.core.exceptions import ServiceUnavailableError


class HealthService:
    """Answers whether the process can actually serve traffic."""

    def __init__(self, session: SessionDep) -> None:
        self._session = session

    async def check_database(self) -> None:
        """Raise `ServiceUnavailableError` unless the database answers.

        OSError is caught alongside SQLAlchemyError deliberately. When the
        database is unreachable, asyncpg raises the asyncio error as-is —
        ConnectionRefusedError, socket.gaierror, TimeoutError — and SQLAlchemy
        never gets to wrap it. Catching only SQLAlchemyError answers 500 for
        the one failure this endpoint exists to report as 503.
        """
        try:
            await self._session.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            raise ServiceUnavailableError("The database is not reachable.") from exc


HealthServiceDep = Annotated[HealthService, Depends()]
