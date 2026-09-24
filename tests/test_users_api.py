"""The profile route.

Users are seeded through the session, never through the API: no endpoint
creates one. A 404 from a database with no user rows is the correct answer
here, not a defect.
"""

import logging
from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskStatus
from app.models import Project, Task, User


def profile_url(username: str) -> str:
    return f"/api/v1/users/{username}/profile"


async def _seed_user_with_work(session: AsyncSession) -> User:
    user = User(username="trung", full_name="Tran Quang Trung")
    owned = Project(name="Owned")
    session.add_all([user, owned, Project(name="Someone else's")])
    await session.flush()

    owned.owner_id = user.id
    session.add_all(
        [
            Task(title="One", project_id=owned.id, assignee_id=user.id),
            Task(title="Two", project_id=owned.id, assignee_id=user.id),
            Task(title="Done", project_id=owned.id, assignee_id=user.id, status=TaskStatus.DONE),
            Task(title="Not theirs", project_id=owned.id),
        ]
    )
    await session.flush()
    return user


async def test_profile_counts_projects_owned_and_tasks_assigned(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    await _seed_user_with_work(db_session)

    body = (await api_client.get(profile_url("trung"))).json()

    assert body["user"]["username"] == "trung"
    assert body["project_count"] == 1, "a project owned by nobody counts toward nobody"
    assert body["task_counts"] == {"todo": 2, "doing": 0, "done": 1}


async def test_every_status_is_present_even_with_no_rows(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """One GROUP BY, then the enum fills the gaps — the client never branches."""
    user = User(username="idle")
    db_session.add(user)
    await db_session.flush()

    body = (await api_client.get(profile_url("idle"))).json()

    assert body["task_counts"] == {"todo": 0, "doing": 0, "done": 0}
    assert body["project_count"] == 0


async def test_the_lookup_ignores_the_case_of_the_url(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """Stored lowercase, looked up lowercase — so `/Trung/` finds `trung`."""
    db_session.add(User(username="trung"))
    await db_session.flush()

    response = await api_client.get(profile_url("TRUNG"))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["user"]["username"] == "trung"


async def test_an_unknown_username_is_a_404_with_its_own_slug(api_client: AsyncClient) -> None:
    response = await api_client.get(profile_url("nobody"))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["type"].endswith("user-not-found")
    assert response.headers["content-type"] == "application/problem+json"


async def test_a_status_the_enum_lost_is_dropped_from_the_counts_but_logged(
    db_session: AsyncSession, api_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The column is VARCHAR so the status set can change without a migration.

    That is the same thing as saying rows will outlive the value they hold.
    `TaskCounts` has one field per member of `TaskStatus` and ignores the rest,
    so such a task stops being counted — and with no `total` in the response,
    a client cannot tell. The log is the only trace, which is why it is pinned
    here rather than left to be noticed in production.
    """
    user = User(username="stale")
    project = Project(name="Holds a retired status")
    db_session.add_all([user, project])
    await db_session.flush()
    db_session.add(Task(title="Current", project_id=project.id, assignee_id=user.id))
    await db_session.flush()
    # Straight to SQL: the schema refuses this value, which is the point — only
    # a status the API once accepted and later retired reaches this state.
    await db_session.execute(
        text(
            "insert into task (title, status, project_id, assignee_id, created_at, updated_at)"
            " values ('Retired', 'cancelled', :p, :u, now(), now())"
        ),
        {"p": project.id, "u": user.id},
    )
    await db_session.flush()

    with caplog.at_level(logging.WARNING, logger="app.services.user"):
        body = (await api_client.get(profile_url("stale"))).json()

    assert body["task_counts"] == {"todo": 1, "doing": 0, "done": 0}, (
        "the retired status is dropped — this asserts the shape as it is, not as it should be"
    )
    assert "cancelled" in caplog.text
    assert "drops 1 task" in caplog.text
