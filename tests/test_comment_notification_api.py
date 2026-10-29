"""`POST /tasks/{task_id}/comments` emails the task's assignee, and nobody else.

Most tests swap the `Mailer` seam for a recorder and assert who was mailed, or
that nobody was. Two go through the real `SmtpMailer` — one to an in-process
SMTP server, one to a closed port — because the recorder cannot show that the
wiring works or that a dead mail server never reaches the client.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mail import Mailer, OutgoingEmail, SmtpMailer, get_mailer
from app.main import app
from app.models import Project, Task, User
from tests.factories import auth_headers, make_user
from tests.servers import free_port, smtp_server


class RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []

    async def send(self, email: OutgoingEmail) -> None:
        self.sent.append(email)


@contextmanager
def using_mailer(mailer: Mailer) -> Iterator[None]:
    app.dependency_overrides[get_mailer] = lambda: mailer
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_mailer, None)


@pytest.fixture
def outbox() -> Iterator[list[OutgoingEmail]]:
    mailer = RecordingMailer()
    with using_mailer(mailer):
        yield mailer.sent


def comments_url(task_id: int) -> str:
    return f"/api/v1/tasks/{task_id}/comments"


def _smtp_mailer(port: int) -> SmtpMailer:
    return SmtpMailer(
        hostname="127.0.0.1",
        port=port,
        username=None,
        password=None,
        use_tls=False,
        timeout=2,
        sender="TaskHub <noreply@taskhub.local>",
    )


async def _seed(
    db_session: AsyncSession, *, assignee: User | None, author: User | None = None
) -> tuple[User, Task]:
    """A task assigned to `assignee`; returns the commenting author and the task."""
    project = Project(name="Holder")
    author = author or make_user("commenter")
    users = [author, *([assignee] if assignee and assignee is not author else [])]
    db_session.add_all([project, *users])
    await db_session.flush()
    task = Task(
        title="Ship it",
        project_id=project.id,
        assignee_id=assignee.id if assignee else None,
    )
    db_session.add(task)
    await db_session.flush()
    return author, task


async def test_a_comment_emails_the_tasks_assignee(
    db_session: AsyncSession, api_client: AsyncClient, outbox: list[OutgoingEmail]
) -> None:
    assignee = make_user("worker", email="worker@example.com")
    author, task = await _seed(db_session, assignee=assignee)

    response = await api_client.post(
        comments_url(task.id), json={"content": "please look"}, headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.CREATED
    [email] = outbox
    assert email.to == "worker@example.com"
    assert f"#{task.id}" in email.subject
    assert all(part in email.body for part in ("commenter", "Ship it", "please look"))
    assert email.reference == f"task {task.id}, comment {response.json()['id']}"


@pytest.mark.parametrize(
    "case",
    ["unassigned", "assignee-is-the-author", "assignee-has-no-email", "assignee-is-disabled"],
)
async def test_no_email_is_sent_when(
    case: str,
    db_session: AsyncSession,
    api_client: AsyncClient,
    outbox: list[OutgoingEmail],
) -> None:
    author: User | None = None
    assignee: User | None
    match case:
        case "unassigned":
            assignee = None
        case "assignee-is-the-author":
            assignee = author = make_user("commenter", email="commenter@example.com")
        case "assignee-has-no-email":
            assignee = make_user("worker")
        case _:
            assignee = make_user("worker", email="worker@example.com", is_active=False)
    author, task = await _seed(db_session, assignee=assignee, author=author)

    response = await api_client.post(
        comments_url(task.id), json={"content": "hi"}, headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.CREATED
    assert outbox == []


async def test_a_refused_comment_sends_nothing(
    db_session: AsyncSession, api_client: AsyncClient, outbox: list[OutgoingEmail]
) -> None:
    assignee = make_user("worker", email="worker@example.com")
    author, _ = await _seed(db_session, assignee=assignee)

    response = await api_client.post(
        comments_url(999_999), json={"content": "hi"}, headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert outbox == []


async def test_with_email_disabled_the_comment_is_201_and_no_task_is_queued(
    db_session: AsyncSession, api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[object] = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, *a, **kw: queued.append(a))
    assignee = make_user("worker", email="worker@example.com")
    author, task = await _seed(db_session, assignee=assignee)

    response = await api_client.post(
        comments_url(task.id), json={"content": "hi"}, headers=auth_headers(author)
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["content"] == "hi"
    assert queued == []


async def test_the_email_reaches_a_real_smtp_server(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    assignee = make_user("worker", email="worker@example.com")
    author, task = await _seed(db_session, assignee=assignee)

    with smtp_server() as inbox, using_mailer(_smtp_mailer(inbox.port)):
        response = await api_client.post(
            comments_url(task.id), json={"content": "over the wire"}, headers=auth_headers(author)
        )

        assert response.status_code == HTTPStatus.CREATED
        [envelope] = inbox.envelopes
        assert envelope.rcpt_tos == ["worker@example.com"]
        [message] = inbox.messages
        assert f"#{task.id}" in message["Subject"]
        assert "over the wire" in message.get_payload()


async def test_an_unreachable_smtp_server_still_answers_201_and_logs_the_ids(
    db_session: AsyncSession, api_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    assignee = make_user("worker", email="worker@example.com")
    author, task = await _seed(db_session, assignee=assignee)
    with using_mailer(_smtp_mailer(free_port())), caplog.at_level(logging.ERROR, "app.core.mail"):
        response = await api_client.post(
            comments_url(task.id), json={"content": "hi"}, headers=auth_headers(author)
        )

    assert response.status_code == HTTPStatus.CREATED
    [record] = [r for r in caplog.records if r.name == "app.core.mail"]
    assert f"task {task.id}, comment {response.json()['id']}" in record.getMessage()
    assert "worker@example.com" not in caplog.text
