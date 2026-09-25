"""Reading a list must not cost more statements because the list is longer.

That is the whole definition of N+1, and it is what this file pins. The
assertion is an **equality between two requests**, not a threshold: one page of
1 task and one page of 20 tasks must emit the same number of SELECTs.

The distinction matters. A threshold — "at most 4 statements" — is a magic
number that breaks the day someone adds a legitimate join, and the cheapest way
to make it green again is to raise it, which retires the test without anyone
deciding to. An equality only breaks when cost actually starts tracking row
count, which is the defect itself.

For the record, measured: eager loading costs 4 statements whatever the page
holds — the project existence check, the task SELECT with the assignee joined
in, the `selectin` SELECT for tags, and the COUNT. Lazy loading 20 tasks would
cost 1 + 20 + 20 = 41: the task SELECT, then one per task for its tags and one
per task for its assignee.

This test sees 3 of those 4, and the gap is worth knowing about. `api_client`
hands the request the same session the seeding used, so the project is already
in the identity map and `ProjectService.get` answers without touching the
database at all. A production request gets a fresh session and pays for that
lookup. The invariant is untouched either way — 4 equals 4 as surely as 3
equals 3 — but a number read out of this file is the harness's, not the
endpoint's.

Two different defects trip this test, and they trip it differently. Removing an
eager option makes it red by raising MissingGreenlet during serialisation —
under AsyncSession a forgotten option is a 500, so the lazy path never survives
long enough to be counted, and the equality assertion is not what catches it.
What the equality assertion catches is the other shape: a query issued once per
row somewhere above the repository, which raises nothing at all. Verified by
introducing one — a loop calling a count per task — and reading the result:
`4 statements for 1 task, 23 for 20`. The assertion is not decorative; it
covers the half that fails quietly.

This sits beside `test_schema_matches_columns.py` and `test_openapi_document.py`
for the same reason they exist: the ordinary suite cannot see any of it. Strip
the eager options and every other test stays green while the database quietly
does forty times the work.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Project, Tag, Task, User


@contextmanager
def count_selects(engine: AsyncEngine) -> Iterator[list[str]]:
    """Every SELECT the driver actually sent, while the block runs.

    `before_cursor_execute` fires once per statement, after the ORM has decided
    everything — so it cannot be fooled by a query that was planned and then
    skipped, nor by a result served from the identity map.

    `event.remove` in a `finally` is not tidiness: the engine is session-scoped,
    and a listener left attached would go on counting statements for every test
    that follows.
    """
    statements: list[str] = []

    def before_cursor_execute(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


async def _project_with_tasks(session: AsyncSession, name: str, count: int) -> Project:
    """One project, `count` tasks, every task assigned and wearing both tags."""
    project = Project(name=name)
    user = User(username=f"owner-{name.lower()}")
    tags = [Tag(name=f"{name}-a"), Tag(name=f"{name}-b")]
    session.add_all([project, user, *tags])
    await session.flush()

    for i in range(count):
        task = Task(title=f"{name} {i}", project_id=project.id, assignee_id=user.id)
        task.tags = tags
        session.add(task)
    await session.flush()
    return project


async def test_the_statement_count_does_not_grow_with_the_number_of_tasks(
    db_session: AsyncSession, api_client: AsyncClient, _engine: AsyncEngine
) -> None:
    small = await _project_with_tasks(db_session, "Small", 1)
    large = await _project_with_tasks(db_session, "Large", 20)

    # The counter opens immediately before each request and closes immediately
    # after: the seeding above runs on the same connection, and its inserts
    # would otherwise land in the total.
    with count_selects(_engine) as for_one:
        one = await api_client.get(f"/api/v1/projects/{small.id}/tasks", params={"size": 100})
    with count_selects(_engine) as for_twenty:
        twenty = await api_client.get(f"/api/v1/projects/{large.id}/tasks", params={"size": 100})

    # Before comparing them: a counter listening to the wrong engine collects
    # nothing, and `0 == 0` would pass while proving nothing at all.
    assert for_one, "the counter saw no statements — it is not listening to the engine under test"

    assert len(for_one) == len(for_twenty), (
        f"{len(for_one)} statements for 1 task, {len(for_twenty)} for 20 — "
        f"the cost is tracking the row count, which is what N+1 means"
    )

    # Alongside the invariant, because an endpoint that returns nothing would
    # satisfy it perfectly.
    assert one.json()["total"] == 1
    assert len(twenty.json()["items"]) == 20
    assert all(len(item["tags"]) == 2 for item in twenty.json()["items"])
    assert all(item["assignee"] is not None for item in twenty.json()["items"])
