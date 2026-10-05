"""In-process servers for tests that must cross a real socket.

Mail is checked against an `aiosmtpd` server rather than a mock: the point of
the SMTP tests is that `aiosmtplib` really speaks the protocol, and a mocked
client would keep them green however the wiring broke.
"""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from email import message_from_bytes
from email.message import Message

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session


def free_port() -> int:
    """A port nothing is listening on right now.

    Bound to 0 so the OS picks, read, then released. Doubles as the "closed
    port" for tests of an unreachable service. There is a window in which
    another process could take it; locally that does not happen.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SmtpInbox:
    """Collects every message the SMTP server accepts, with its envelope."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.envelopes: list[Envelope] = []

    @property
    def messages(self) -> list[Message]:
        # `content` is bytes for a DATA command; aiosmtpd types it as bytes | str.
        return [
            message_from_bytes(
                envelope.content.encode()
                if isinstance(envelope.content, str)
                else envelope.content or b""
            )
            for envelope in self.envelopes
        ]

    # aiosmtpd looks the hook up by this exact name.
    async def handle_DATA(  # noqa: N802
        self, server: SMTP, session: Session, envelope: Envelope
    ) -> str:
        # DATA is acknowledged only after this returns, so a message is in the
        # list before `aiosmtplib.send` does.
        self.envelopes.append(envelope)
        return "250 OK"


@contextmanager
def smtp_server() -> Iterator[SmtpInbox]:
    """Run an SMTP server on a free port for the duration of the block.

    aiosmtpd 1.4.6 cannot be given port 0 on Python 3.12 (its start-up probe
    connects to the port it was asked for), hence `free_port()`. The server
    runs its own loop in a daemon thread, independent of pytest-asyncio's.
    """
    inbox = SmtpInbox(free_port())
    controller = Controller(inbox, hostname="127.0.0.1", port=inbox.port)
    controller.start()
    try:
        yield inbox
    finally:
        controller.stop()
