"""The two task routes, end to end."""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskStatus
from app.models import Project, Tag, Task, User


def tasks_url(project_id: int) -> str:
    return f"/api/v1/projects/{project_id}/tasks"


async def _seed(session: AsyncSession) -> tuple[Project, User, list[Tag]]:
    project = Project(name="Holder")
    user = User(username="worker", full_name="A Worker")
    tags = [Tag(name="urgent"), Tag(name="backend")]
    session.add_all([project, user, *tags])
    await session.flush()
    return project, user, tags


async def test_create_returns_the_task_with_its_tags_and_assignee(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """The nested edges have to be in the response, not just in the database."""
    project, user, tags = await _seed(db_session)

    response = await api_client.post(
        tasks_url(project.id),
        json={
            "title": "Write the migration",
            "status": TaskStatus.DOING,
            "assignee_id": user.id,
            "tag_ids": [tag.id for tag in tags],
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["title"] == "Write the migration"
    assert body["status"] == "doing"
    assert body["assignee"]["username"] == "worker"
    assert {tag["name"] for tag in body["tags"]} == {"urgent", "backend"}


async def test_create_without_an_assignee_or_tags_is_ordinary(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)

    body = (await api_client.post(tasks_url(project.id), json={"title": "Bare"})).json()

    assert body["assignee"] is None
    assert body["tags"] == []
    assert body["status"] == "todo"


async def test_list_paginates_and_counts_every_match(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)
    for i in range(5):
        await api_client.post(tasks_url(project.id), json={"title": f"Task {i}"})

    page = (await api_client.get(tasks_url(project.id), params={"page": 2, "size": 2})).json()

    assert page["total"] == 5
    assert page["pages"] == 3
    assert len(page["items"]) == 2


async def test_list_and_create_404_for_a_project_that_does_not_exist(
    api_client: AsyncClient,
) -> None:
    listed = await api_client.get(tasks_url(999_999))
    created = await api_client.post(tasks_url(999_999), json={"title": "Orphan"})

    assert listed.status_code == HTTPStatus.NOT_FOUND
    assert created.status_code == HTTPStatus.NOT_FOUND
    # The slug, not just the status: it is what a client branches on.
    assert listed.json()["type"].endswith("project-not-found")


async def test_an_unknown_assignee_is_a_422_naming_it(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)

    response = await api_client.post(
        tasks_url(project.id), json={"title": "Nobody's", "assignee_id": 999_999}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("assignee-not-found")
    assert "999999" in response.json()["detail"]


async def test_an_unknown_tag_id_is_a_422_naming_it(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """Left to the database this would be a generic 409 naming nothing."""
    project, _, tags = await _seed(db_session)

    response = await api_client.post(
        tasks_url(project.id), json={"title": "Mislabelled", "tag_ids": [tags[0].id, 999_999]}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["type"].endswith("unknown-tag-ids")
    assert "999999" in response.json()["detail"]


async def test_too_many_tag_ids_is_refused_by_the_schema(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """The cap exists because this list becomes an `IN` clause."""
    project, _, _ = await _seed(db_session)

    response = await api_client.post(
        tasks_url(project.id), json={"title": "Greedy", "tag_ids": list(range(1, 50))}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "tag_ids"


# The two below exercise project endpoints, but what they pin is task
# behaviour: both only exist because a project can now hold tasks. They live
# with the tasks rather than with the projects for that reason.

PROJECTS = "/api/v1/projects"


async def test_delete_is_refused_while_the_project_still_has_tasks(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """The RESTRICT is conditional, not permanent — clear the tasks and it goes.

    Behaviour change: this endpoint used to answer 204 unconditionally.
    """
    project = Project(name="Occupied")
    db_session.add(project)
    await db_session.flush()
    db_session.add(task := Task(title="In the way", project_id=project.id))
    await db_session.flush()

    refused = await api_client.delete(f"{PROJECTS}/{project.id}")

    assert refused.status_code == HTTPStatus.CONFLICT
    assert refused.headers["content-type"] == "application/problem+json"
    # Its own slug, so a client can tell this apart from a duplicate name —
    # every IntegrityError otherwise renders as the same generic conflict.
    assert refused.json()["type"].endswith("project-has-tasks")
    assert "1 task" in refused.json()["detail"]

    await db_session.delete(task)
    await db_session.flush()

    assert (
        await api_client.delete(f"{PROJECTS}/{project.id}")
    ).status_code == HTTPStatus.NO_CONTENT


async def test_detail_reports_how_many_tasks_hang_off_the_project(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project = Project(name="Counted")
    db_session.add(project)
    await db_session.flush()
    db_session.add_all([Task(title=f"T{i}", project_id=project.id) for i in range(3)])
    await db_session.flush()

    assert (await api_client.get(f"{PROJECTS}/{project.id}")).json()["total_tasks"] == 3
