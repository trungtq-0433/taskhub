"""The API's length limits must not exceed the columns behind them.

Sharing a constant makes the two sides agree today. This is what notices when
someone stops sharing it — a literal typed back into a schema, a column widened
without the schema following.

The failure being guarded against is not cosmetic. A schema that accepts more
than the column holds sends the overlong value to the database, which rejects
it, and the client is told 500 `database-error` for a mistake that was its own
and that validation could have named. The alerting agrees with the 500.
"""

from typing import Any

import pytest
from annotated_types import MaxLen, MinLen
from pydantic import BaseModel
from sqlalchemy import String

from app.models import Project, Tag, Task, User
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.tag import TagCreate, TagUpdate
from app.schemas.task import TaskCreate
from app.schemas.user import UserRegister, UserUpdate

# (schema, field, model, column) — every string field that maps to a column
# with a width. `description` is omitted on purpose: its column is TEXT, so
# there is nothing on the database side to exceed.
MAPPINGS = [
    (ProjectCreate, "name", Project, "name"),
    (ProjectUpdate, "name", Project, "name"),
    (TagCreate, "name", Tag, "name"),
    (TagUpdate, "name", Tag, "name"),
    (TagCreate, "color", Tag, "color"),
    (TagUpdate, "color", Tag, "color"),
    (TaskCreate, "title", Task, "title"),
    (UserRegister, "username", User, "username"),
    (UserRegister, "full_name", User, "full_name"),
    (UserUpdate, "full_name", User, "full_name"),
]

# `UserRegister.password` is deliberately absent: it has no column of its own
# — `hash_password` turns it into `User.hashed_password` before anything is
# stored, so there is no width on the database side for it to exceed.


def _schema_max_length(schema: type[BaseModel], field: str) -> int | None:
    for constraint in schema.model_fields[field].metadata:
        if isinstance(constraint, MaxLen):
            return constraint.max_length
    return None


def _column_length(model: Any, column: str) -> int | None:
    column_type = model.__table__.c[column].type
    return column_type.length if isinstance(column_type, String) else None


@pytest.mark.parametrize(("schema", "field", "model", "column"), MAPPINGS)
def test_schema_never_accepts_more_than_the_column_holds(
    schema: type[BaseModel], field: str, model: Any, column: str
) -> None:
    limit = _schema_max_length(schema, field)
    width = _column_length(model, column)

    if limit is None:
        # A field with no max_length and a bounded column: any long string the
        # client sends reaches the database and fails there.
        assert width is None, (
            f"{schema.__name__}.{field} has no max_length but "
            f"{model.__name__}.{column} is VARCHAR({width})"
        )
        return

    assert width is not None, f"{schema.__name__}.{field} limits a column that has no width"
    assert limit <= width, (
        f"{schema.__name__}.{field} accepts {limit} characters but "
        f"{model.__name__}.{column} holds {width} — the overflow becomes a 500"
    )


def _schema_min_length(schema: type[BaseModel], field: str) -> int | None:
    for constraint in schema.model_fields[field].metadata:
        if isinstance(constraint, MinLen):
            return constraint.min_length
    return None


@pytest.mark.parametrize(("schema", "field", "model", "column"), MAPPINGS)
def test_a_not_null_column_is_guarded_against_the_empty_string(
    schema: type[BaseModel], field: str, model: Any, column: str
) -> None:
    """NOT NULL does not mean non-empty.

    Postgres stores `''` in a NOT NULL column without complaint, so the
    constraint people reach for does not do the job they expect. The schema's
    min_length is the only thing between a client and a nameless row, which
    makes its absence silent: the row is written, nothing errors, and it
    surfaces later as a blank in a list.
    """
    if model.__table__.c[column].nullable:
        pytest.skip(f"{model.__name__}.{column} is nullable; an empty value is its own answer")

    assert _schema_min_length(schema, field), (
        f"{model.__name__}.{column} is NOT NULL, but {schema.__name__}.{field} "
        f"has no min_length — the empty string reaches the database"
    )
