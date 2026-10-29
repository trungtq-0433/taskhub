"""One log format, on stdout, with the request id on every line.

Everything the process writes — the app's lines, the libraries', uvicorn's
server lines and its access lines — goes to stdout through one handler. The
container runtime collects stdout (`docker compose logs api`) and any log
shipper can read it later without a code change; a file inside the container
would need a volume, write permission for the non-root user and rotation.

Each line carries the `X-Request-ID` of the request being served, `-` outside
one, so a user's screenshot finds every line it caused with one `grep`. That
includes uvicorn's access line: it is written inside the app's `send`, while
`request_id_ctx` is still set (`tests/test_logging_setup.py` runs a real
uvicorn to keep that true across upgrades).

Three details that are easy to undo:

- The filter sits on the handler, not on a logger. A logger's filters do not
  run for records that propagate up from a child logger; a handler's do.
- `disable_existing_loggers` is off. `app.main` imports modules that already
  own a logger before `configure_logging()` runs, and `dictConfig`'s default
  would silence every one of them.
- It runs once, when `app.main` is imported — never in `create_app()`. Tests
  build many apps, and each `dictConfig` would strip pytest's capture handlers
  from the root logger in the middle of a test. uvicorn applies its own logging
  config before it imports the app, so this call is the one that wins.
"""

import logging
import logging.config

from app.core.config import settings
from app.core.middleware import request_id_ctx

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


class RequestIdFilter(logging.Filter):
    """Stamp each record with the id of the request it was written in."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


def resolve_level(log_level: str | None, debug: bool) -> str:
    """`LOG_LEVEL` if set, otherwise DEBUG in debug mode and INFO everywhere else."""
    if log_level is not None:
        return log_level
    return "DEBUG" if debug else "INFO"


def configure_logging() -> None:
    """Route every logger to one stdout handler in `LOG_FORMAT`.

    The level is the root's, so `LOG_LEVEL` governs the app and its libraries.
    uvicorn's loggers keep their own (INFO, or `--log-level`): `LOG_LEVEL=WARNING`
    quiets the app, not the access lines. They lose uvicorn's handlers and
    propagate to the root, which is what puts them in the same format.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {"default": {"format": LOG_FORMAT}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "root": {
                "level": resolve_level(settings.log_level, settings.debug),
                "handlers": ["stdout"],
            },
            "loggers": {
                "uvicorn": {"handlers": [], "propagate": True},
                "uvicorn.access": {"handlers": [], "propagate": True},
            },
        }
    )
