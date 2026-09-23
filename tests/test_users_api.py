"""The profile route.

Users are seeded through the session, never through the API: no endpoint
creates one. A 404 from a database with no user rows is the correct answer
here, not a defect.
"""

from http import HTTPStatus

from httpx import AsyncClient
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
