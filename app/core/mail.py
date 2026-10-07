"""Outgoing email: the seam the rest of the app depends on, and its SMTP implementation.

Callers build an `OutgoingEmail` and hand it to a `Mailer`; they never touch
SMTP. Tests swap the seam with `app.dependency_overrides[get_mailer]`.

`OutgoingEmail` holds plain values only. The request's database session is
closed by the time a background task runs, so everything the message needs
(address, subject, body) is worked out before the response is returned.

`Mailer.send` never raises. Starlette runs background tasks without a `try`:
in production uvicorn logs a traceback and skips the tasks queued after the
failed one, and under httpx's `ASGITransport` the exception comes out of
`await client.post(...)`. A mail server being down is not worth either, so the
failure is logged and dropped; there is no retry.

`reference` is how "which task, which comment" reaches that log line without
the mailer knowing what a comment is. The recipient's address is never logged,
which is why a failure is logged as the reference and the exception's type, with
no message and no traceback: SMTP errors quote the address.
"""

import logging
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Annotated, Protocol, Self

import aiosmtplib
from fastapi import Depends

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """One plain-text message. `reference` is for the failure log only."""

    to: str
    subject: str
    body: str
    reference: str


class Mailer(Protocol):
    async def send(self, email: OutgoingEmail) -> None:
        """Deliver `email`. Must not raise."""
        ...


class SmtpMailer:
    """Sends through an SMTP server with aiosmtplib."""

    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        timeout: float,
        sender: str,
    ) -> None:
        self._hostname = hostname
        self._port = port
        # None, not "": an empty string would still trigger AUTH.
        self._username = username or None
        self._password = password or None
        self._use_tls = use_tls
        self._timeout = timeout
        self._sender = sender

    @classmethod
    def from_settings(cls, config: Settings) -> Self:
        if config.smtp_host is None:
            raise ValueError("SMTP_HOST is not set")
        return cls(
            hostname=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password.get_secret_value() if config.smtp_password else None,
            use_tls=config.smtp_use_tls,
            timeout=config.smtp_timeout,
            sender=config.mail_from,
        )

    async def send(self, email: OutgoingEmail) -> None:
        try:
            message = EmailMessage()
            message["From"] = self._sender
            message["To"] = email.to
            message["Subject"] = email.subject
            message.set_content(email.body)
            await aiosmtplib.send(
                message,
                hostname=self._hostname,
                port=self._port,
                username=self._username,
                password=self._password,
                use_tls=self._use_tls,
                # None: upgrade with STARTTLS when the server offers it. Not
                # allowed alongside implicit TLS, hence False in that case.
                start_tls=False if self._use_tls else None,
                timeout=self._timeout,
            )
        except Exception as exc:  # nothing may escape: see the module docstring
            # Type only: the message and traceback of an SMTP error carry the
            # recipient's address (a 550 reply echoes it back).
            logger.error("Email for %s was not sent (%s)", email.reference, type(exc).__name__)
        else:
            logger.debug("Email for %s was sent", email.reference)


async def get_mailer() -> Mailer | None:
    """The configured mailer, or `None` when email is disabled.

    Reads `settings` on each call, which is what lets tests switch it. Building
    a mailer opens no connection, so doing so per request costs nothing. Async
    for the reason given on `get_tag_service`.
    """
    if settings.smtp_host is None:
        return None
    return SmtpMailer.from_settings(settings)


MailerDep = Annotated[Mailer | None, Depends(get_mailer)]
