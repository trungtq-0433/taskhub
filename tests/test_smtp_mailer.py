"""The SMTP mailer: a real send to an in-process server, and the failure path."""

import logging
from collections.abc import Iterator

import pytest

from app.core.config import settings
from app.core.mail import OutgoingEmail, SmtpMailer, get_mailer
from app.main import app as application
from app.main import lifespan
from tests.servers import SmtpInbox, free_port, smtp_server

RECIPIENT = "an@example.com"


@pytest.fixture(scope="module")
def _inbox_server() -> Iterator[SmtpInbox]:
    with smtp_server() as inbox:
        yield inbox


@pytest.fixture
def inbox(_inbox_server: SmtpInbox) -> SmtpInbox:
    _inbox_server.envelopes.clear()
    return _inbox_server


def _mailer(port: int) -> SmtpMailer:
    return SmtpMailer(
        hostname="127.0.0.1",
        port=port,
        username=None,
        password=None,
        use_tls=False,
        timeout=5,
        sender="TaskHub <noreply@taskhub.local>",
    )


async def test_smtp_mailer_delivers_a_plain_text_message(inbox: SmtpInbox) -> None:
    body = "Có bình luận mới: xin chào"

    await _mailer(inbox.port).send(
        OutgoingEmail(to=RECIPIENT, subject="Task 12", body=body, reference="task 12, comment 34")
    )

    assert [envelope.rcpt_tos for envelope in inbox.envelopes] == [[RECIPIENT]]
    (message,) = inbox.messages
    assert message["From"] == "TaskHub <noreply@taskhub.local>"
    assert message["To"] == RECIPIENT
    assert message["Subject"] == "Task 12"
    assert message.get_content_type() == "text/plain"
    assert message.get_content_charset() == "utf-8"
    assert message.get_payload(decode=True).decode("utf-8").strip() == body  # type: ignore[union-attr]


async def test_an_unreachable_server_is_logged_with_the_reference_and_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mailer = _mailer(free_port())

    with caplog.at_level(logging.ERROR, logger="app.core.mail"):
        await mailer.send(
            OutgoingEmail(to=RECIPIENT, subject="s", body="b", reference="task 12, comment 34")
        )

    (record,) = [r for r in caplog.records if r.name == "app.core.mail"]
    assert record.levelno == logging.ERROR
    assert "task 12, comment 34" in record.getMessage()
    assert RECIPIENT not in caplog.text


async def test_a_refused_recipient_is_logged_without_the_address_and_never_raised(
    inbox: SmtpInbox, caplog: pytest.LogCaptureFixture
) -> None:
    # Servers echo the address back in the 550 reply, and aiosmtplib puts that
    # reply in the exception: logging the exception would log the address.
    inbox.refuse_rcpt_with = "550 5.1.1 <{address}> no such user"
    try:
        with caplog.at_level(logging.DEBUG, logger="app.core.mail"):
            await _mailer(inbox.port).send(
                OutgoingEmail(to=RECIPIENT, subject="s", body="b", reference="task 12, comment 34")
            )
    finally:
        inbox.refuse_rcpt_with = None

    # Only the mailer's records: the in-process server logs the address itself.
    (record,) = [r for r in caplog.records if r.name == "app.core.mail"]
    assert record.levelno == logging.ERROR
    assert "task 12, comment 34" in record.getMessage()
    assert "SMTPRecipientsRefused" in record.getMessage()
    assert record.exc_info is None
    assert RECIPIENT not in record.getMessage()
    assert RECIPIENT not in str(record.__dict__)


async def test_get_mailer_is_none_without_smtp_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)

    assert await get_mailer() is None


async def test_get_mailer_builds_an_smtp_mailer_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.test")

    mailer = await get_mailer()

    assert isinstance(mailer, SmtpMailer)


async def test_startup_logs_that_email_is_disabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)

    with caplog.at_level(logging.INFO, logger="app.main"):
        async with lifespan(application):
            pass

    lines = [r.getMessage() for r in caplog.records if "Email notifications" in r.getMessage()]
    assert lines == ["Email notifications disabled: SMTP_HOST is not set"]
