"""The whole API in one chained flow: register, log in, work a task, clean up.

Two users register, one logs in, creates a project and a tag, then a task that
carries the tag. She assigns it to the other user and comments on it (the
assignee gets an email), filters the task list, bookmarks the task and deletes
her comment. Each step asserts its status and the fields the next step reads,
so a broken link fails where it broke.

The tag is created *before* the task: no route attaches a tag to an existing
task (tags ride in on `tag_ids` at creation) and `GET /tasks` filters only by
`status` and `priority`. The narrower register-and-create flow is
`test_register_and_create_task_flow.py`; the error cases live in the per-router
test files.
"""

from http import HTTPStatus

from httpx import AsyncClient

from tests.factories import TEST_PASSWORD
from tests.test_comment_notification_api import RecordingMailer, using_mailer

API = "/api/v1"


async def test_the_api_from_registration_to_cleanup(api_client: AsyncClient) -> None:
    ids: dict[str, int] = {}
    for name, address in (("alice", "alice@example.com"), ("bob", "Bob@Example.com")):
        registered = await api_client.post(
            f"{API}/users/register",
            json={
                "username": name,
                "password": TEST_PASSWORD,
                "full_name": name.title(),
                "email": address,
            },
        )
        assert registered.status_code == HTTPStatus.CREATED
        assert registered.json()["email"] == address.lower()
        ids[name] = registered.json()["id"]

    login = await api_client.post(
        f"{API}/users/login", data={"username": "alice", "password": TEST_PASSWORD}
    )
    assert login.status_code == HTTPStatus.OK
    alice = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await api_client.get(f"{API}/users/me", headers=alice)
    assert me.status_code == HTTPStatus.OK
    assert me.json()["id"] == ids["alice"]

    project = await api_client.post(f"{API}/projects", json={"name": "A-Z project"})
    assert project.status_code == HTTPStatus.CREATED

    tag = await api_client.post(f"{API}/tags", json={"name": "urgent", "color": "#FF0000"})
    assert tag.status_code == HTTPStatus.CREATED
    tag_id = tag.json()["id"]

    created = await api_client.post(
        f"{API}/projects/{project.json()['id']}/tasks",
        json={"title": "Ship the API", "priority": "high", "tag_ids": [tag_id]},
    )
    assert created.status_code == HTTPStatus.CREATED
    assert [t["id"] for t in created.json()["tags"]] == [tag_id]
    assert created.json()["assignee"] is None
    task_id = created.json()["id"]

    assigned = await api_client.post(
        f"{API}/tasks/{task_id}/assign", json={"assignee_id": ids["bob"]}, headers=alice
    )
    assert assigned.status_code == HTTPStatus.OK
    assert assigned.json()["assignee"]["id"] == ids["bob"]

    recorder = RecordingMailer()
    with using_mailer(recorder):
        comment = await api_client.post(
            f"{API}/tasks/{task_id}/comments", json={"content": "please look"}, headers=alice
        )
    assert comment.status_code == HTTPStatus.CREATED
    [email] = recorder.sent
    assert email.to == "bob@example.com", "the assignee, not the author, is mailed"

    filtered = await api_client.get(f"{API}/tasks", params={"status": "todo", "priority": "high"})
    assert filtered.status_code == HTTPStatus.OK
    task = next(item for item in filtered.json()["items"] if item["id"] == task_id)
    assert [t["name"] for t in task["tags"]] == ["urgent"]
    assert task["assignee"]["id"] == ids["bob"]

    other = await api_client.get(f"{API}/tasks", params={"priority": "low"})
    assert other.status_code == HTTPStatus.OK
    assert task_id not in [item["id"] for item in other.json()["items"]]

    bookmarked = await api_client.post(f"{API}/tasks/{task_id}/bookmark", headers=alice)
    assert bookmarked.status_code == HTTPStatus.CREATED
    assert bookmarked.json()["task_id"] == task_id

    deleted = await api_client.delete(
        f"{API}/tasks/{task_id}/comments/{comment.json()['id']}", headers=alice
    )
    assert deleted.status_code == HTTPStatus.NO_CONTENT
