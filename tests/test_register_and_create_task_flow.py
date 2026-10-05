"""Register, log in, then create a task assigned to yourself — one chained flow.

Each step consumes the previous step's output (the registered id becomes the
`assignee_id`, the token authorises `/me`, the project id builds the task URL),
so a broken link fails at the step that broke. The error cases live in
`test_auth_api.py` and `test_tasks_api.py`.

The client is `httpx.AsyncClient` over `ASGITransport` (the `api_client`
fixture), not FastAPI's `TestClient`: the app is async end to end on asyncpg,
FastAPI's "Async Tests" guide prescribes this pairing, and `TestClient` runs the
app on its own event loop in a thread, so it could not share the test's
`db_session` and its rollback.
"""

from http import HTTPStatus

from httpx import AsyncClient

from tests.factories import TEST_PASSWORD

REGISTER_URL = "/api/v1/users/register"
LOGIN_URL = "/api/v1/users/login"
ME_URL = "/api/v1/users/me"
PROJECTS_URL = "/api/v1/projects"
TASKS_URL = "/api/v1/tasks"


async def test_a_new_user_registers_logs_in_and_gets_a_task_assigned(
    api_client: AsyncClient,
) -> None:
    registered = await api_client.post(
        REGISTER_URL,
        json={
            "username": "flow-user",
            "password": TEST_PASSWORD,
            "full_name": "Flow User",
            "email": "Flow.User@Example.com",
        },
    )
    assert registered.status_code == HTTPStatus.CREATED
    user = registered.json()
    assert user["email"] == "flow.user@example.com", "the email is lowercased on the way in"

    login = await api_client.post(
        LOGIN_URL, data={"username": "flow-user", "password": TEST_PASSWORD}
    )
    assert login.status_code == HTTPStatus.OK
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await api_client.get(ME_URL, headers=headers)
    assert me.status_code == HTTPStatus.OK
    assert me.json()["id"] == user["id"]
    assert me.json()["email"] == "flow.user@example.com"

    project = await api_client.post(PROJECTS_URL, json={"name": "Flow project"})
    assert project.status_code == HTTPStatus.CREATED
    project_id = project.json()["id"]

    created = await api_client.post(
        f"{PROJECTS_URL}/{project_id}/tasks",
        json={"title": "First task", "assignee_id": user["id"]},
    )
    assert created.status_code == HTTPStatus.CREATED
    assert created.json()["assignee"]["id"] == user["id"]
    task_id = created.json()["id"]

    listed = await api_client.get(TASKS_URL)
    assert listed.status_code == HTTPStatus.OK
    task = next(item for item in listed.json()["items"] if item["id"] == task_id)
    assert task["project_id"] == project_id
    assert task["title"] == "First task"
    assert task["assignee"] == {
        "id": user["id"],
        "username": "flow-user",
        "full_name": "Flow User",
    }, "the nested assignee never carries the email"
