"""`GET /tasks`: fastapi-filter's `status`/`priority`, and fastapi-pagination's
`page`/`size`.

Split out of `test_tasks_api.py`, which already covers the nested
list/create route and would grow past this codebase's file-size ceiling if
this surface stayed folded in.
"""

from http import HTTPStatus

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TaskPriority, TaskStatus
from app.models import Project, Tag, User
from tests.factories import make_user

ALL_TASKS = "/api/v1/tasks"


def tasks_url(project_id: int) -> str:
    return f"/api/v1/projects/{project_id}/tasks"


async def _seed(session: AsyncSession) -> tuple[Project, User, list[Tag]]:
    project = Project(name="Holder")
    user = make_user("worker", full_name="A Worker")
    tags = [Tag(name="urgent"), Tag(name="backend")]
    session.add_all([project, user, *tags])
    await session.flush()
    return project, user, tags


async def test_status_filter_is_case_insensitive_and_matches_only_that_status(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """The proof that FastAPI honours `BeforeValidator` inside `Annotated[..., Query()]`.

    If this fails, the filter mechanism itself is broken, and nothing built on
    top of it can be trusted either.
    """
    project, _, _ = await _seed(db_session)
    await api_client.post(
        tasks_url(project.id), json={"title": "A todo", "status": TaskStatus.TODO}
    )
    await api_client.post(
        tasks_url(project.id), json={"title": "A done", "status": TaskStatus.DONE}
    )

    response = await api_client.get(ALL_TASKS, params={"status": "TODO"})

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["A todo"]
    assert all(item["status"] == "todo" for item in body["items"])


async def test_an_unknown_status_value_is_a_422_naming_the_field_and_the_choices(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get(ALL_TASKS, params={"status": "urgent"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = response.json()
    assert body["errors"][0]["field"] == "status"
    assert "todo" in body["errors"][0]["message"]
    assert "doing" in body["errors"][0]["message"]
    assert "done" in body["errors"][0]["message"]


async def test_an_empty_status_value_is_a_422(api_client: AsyncClient) -> None:
    response = await api_client.get(ALL_TASKS, params={"status": ""})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["errors"][0]["field"] == "status"


async def test_the_nested_list_ignores_status_because_it_takes_no_filters(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """Decision: filters are `GET /tasks` only — the nested route never reads
    `status`/`priority` from the query string at all."""
    project, _, _ = await _seed(db_session)
    await api_client.post(tasks_url(project.id), json={"title": "Todo one"})
    await api_client.post(tasks_url(project.id), json={"title": "Done one", "status": "done"})

    page = (await api_client.get(tasks_url(project.id), params={"status": "todo"})).json()

    assert page["total"] == 2


async def test_list_all_tasks_spans_every_project(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    first, _, _ = await _seed(db_session)
    second = Project(name="Second holder")
    db_session.add(second)
    await db_session.flush()

    await api_client.post(tasks_url(first.id), json={"title": "In first"})
    await api_client.post(tasks_url(second.id), json={"title": "In second"})

    response = await api_client.get(ALL_TASKS)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert {item["title"] for item in body["items"]} == {"In first", "In second"}
    assert body["total"] == 2


async def test_status_and_priority_filters_and_together(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)
    await api_client.post(
        tasks_url(project.id),
        json={"title": "todo-high", "status": TaskStatus.TODO, "priority": TaskPriority.HIGH},
    )
    await api_client.post(
        tasks_url(project.id),
        json={"title": "todo-low", "status": TaskStatus.TODO, "priority": TaskPriority.LOW},
    )
    await api_client.post(
        tasks_url(project.id),
        json={"title": "done-high", "status": TaskStatus.DONE, "priority": TaskPriority.HIGH},
    )

    response = await api_client.get(ALL_TASKS, params={"status": "todo", "priority": "high"})

    assert [item["title"] for item in response.json()["items"]] == ["todo-high"]


async def test_the_top_level_list_defaults_to_size_50(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    project, _, _ = await _seed(db_session)
    await api_client.post(tasks_url(project.id), json={"title": "Solo"})

    page = (await api_client.get(ALL_TASKS)).json()

    assert page["size"] == 50


async def test_the_top_level_list_size_is_capped_at_100(api_client: AsyncClient) -> None:
    response = await api_client.get(ALL_TASKS, params={"size": 101})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_the_top_level_list_rejects_page_zero(api_client: AsyncClient) -> None:
    response = await api_client.get(ALL_TASKS, params={"page": 0})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_unknown_skip_and_limit_are_ignored_and_the_default_page_is_served(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    """`skip`/`limit` are not this API's pagination parameters — fastapi-pagination
    only knows `page`/`size`, so unrecognised query params are silently dropped."""
    project, _, _ = await _seed(db_session)
    await api_client.post(tasks_url(project.id), json={"title": "One"})

    response = await api_client.get(ALL_TASKS, params={"skip": 10, "limit": 5})

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["size"] == 50
    assert body["total"] == 1
