"""The nested route's two behaviour changes from this PR: `priority` on
create, and fastapi-pagination's own `page`/`size` defaults.

Split out of `test_tasks_api.py` to keep that file looking untouched by this
PR outside of what the nested route's response shape actually requires —
these are new tests, not edits to existing ones.
"""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskPriority
from app.models import Project, Tag, User
from tests.factories import make_user


def tasks_url(project_id: int) -> str:
    return f"/api/v1/projects/{project_id}/tasks"


async def _seed(session: AsyncSession) -> tuple[Project, User, list[Tag]]:
    project = Project(name="Holder")
    user = make_user("worker", full_name="A Worker")
    tags = [Tag(name="urgent"), Tag(name="backend")]
    session.add_all([project, user, *tags])
    await session.flush()
    return project, user, tags


async def test_a_task_created_without_priority_defaults_to_medium(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)

    response = await api_client.post(tasks_url(project.id), json={"title": "No priority set"})

    assert response.json()["priority"] == "medium"


async def test_create_accepts_an_explicit_priority(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)

    response = await api_client.post(
        tasks_url(project.id), json={"title": "Urgent one", "priority": TaskPriority.HIGH}
    )

    assert response.json()["priority"] == "high"


async def test_the_nested_list_defaults_to_size_50(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)
    await api_client.post(tasks_url(project.id), json={"title": "Solo"})

    page = (await api_client.get(tasks_url(project.id))).json()

    assert page["size"] == 50


async def test_the_nested_list_refuses_a_page_past_the_ceiling(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """On `main` this route capped `page` at 100,000 and answered 422; moving it
    onto fastapi-pagination must not turn the same request into a 500."""
    project, _, _ = await _seed(db_session)

    response = await api_client.get(tasks_url(project.id), params={"page": 10**18})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "page"
