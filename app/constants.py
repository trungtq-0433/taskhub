"""Values the database layer and the API layer both have to agree on.

A value that appears in a model and again in a schema is a value that can drift:
change the model's default and the schema keeps validating against the old set,
so rows get written that the API then refuses to read back. Declaring it once,
here, removes the second copy rather than keeping the two in step by hand.

`StrEnum` rather than `Enum`: members *are* strings, so SQLAlchemy stores
`ProjectStatus.ACTIVE` as `"active"` with no converter, Pydantic accepts the
plain string a client sends, and the JSON on the wire is unchanged.
"""

from enum import StrEnum


class ProjectStatus(StrEnum):
    """Allowed values for `project.status`.

    The column stays `VARCHAR`. This is the Python side of the contract, not a
    Postgres `ENUM` type — those cannot drop a value (`ALTER TYPE ... DROP
    VALUE` does not exist) and Alembic does not diff their members, so changing
    the set produces an empty migration.

    The database therefore does not enforce this set; only the API layer does.
    A raw `INSERT` can still write anything. Closing that gap wants a `CHECK`
    constraint, which is a separate migration and a separate decision.
    """

    ACTIVE = "active"
    ARCHIVED = "archived"


# Column widths. The model and the schemas have to agree on these, and the
# failure when they do not is worse than it looks: a schema that accepts more
# than the column holds turns a client's overlong string into a 500 from the
# database instead of a 422 from validation. The client is told the server
# broke, and the alerting agrees with it.
#
# These are not settings. They do not vary by environment — changing one is a
# schema change and a migration, not a deployment knob — so they do not belong
# in app/core/config.py.
# NOT NULL does not exclude the empty string — Postgres stores '' happily —
# so this is the only thing standing between a client and a nameless row.
NAME_MIN_LENGTH = 1

PROJECT_NAME_MAX_LENGTH = 200
TAG_NAME_MAX_LENGTH = 50

# Wider than the longest value ProjectStatus holds today ("archived", 8),
# so adding a status is a Python change rather than a migration. Not derived
# from the enum: a computed width would change the DDL whenever the enum
# gained a longer member, and autogenerate would demand a migration nobody
# asked for.
PROJECT_STATUS_MAX_LENGTH = 20

# `#RRGGBB`, so seven characters. The schema validates the shape with a regex;
# this is the column that has to hold the result.
TAG_COLOR_LENGTH = 7

# API-side only: the column is TEXT and has no limit of its own. A ceiling
# exists so one request cannot post a novel, not because storage requires it.
PROJECT_DESCRIPTION_MAX_LENGTH = 10_000


class TaskStatus(StrEnum):
    """Allowed values for `task.status`.

    VARCHAR for the same reason as `ProjectStatus`: a Postgres `ENUM` cannot
    drop a value and Alembic does not diff its members, so changing the set
    would autogenerate an empty migration. The database does not enforce this
    set; only the API layer does.
    """

    TODO = "todo"
    DOING = "doing"
    DONE = "done"


TASK_TITLE_MAX_LENGTH = 200

# Wider than the longest value TaskStatus holds today ("doing", 5), for the
# same reason PROJECT_STATUS_MAX_LENGTH is wider than "archived".
TASK_STATUS_MAX_LENGTH = 20

# API-side only, like the project's — the column is TEXT.
TASK_DESCRIPTION_MAX_LENGTH = 10_000

USERNAME_MAX_LENGTH = 50
FULL_NAME_MAX_LENGTH = 100

# bcrypt's own ceiling: bytes 73+ of the input are silently ignored by the
# reference algorithm, and this library raises `ValueError` instead of quietly
# truncating. It is a byte count, not a character count — the schema that
# enforces it must encode to UTF-8 before measuring.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72

# bcrypt's encoded output (`$2b$<cost>$<22-char salt><31-char hash>`) is always
# exactly 60 characters, regardless of cost factor or input length.
HASHED_PASSWORD_LENGTH = 60

# A client-supplied list becomes an `IN` clause, so it needs a ceiling. Twenty
# tags on one task is already well past what anyone reads.
TASK_MAX_TAGS = 20
