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
