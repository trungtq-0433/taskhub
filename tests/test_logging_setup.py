"""One log format on stdout, with the request id on every line.

The level rule is unit-tested. Everything else is proven against a real
`uvicorn` process, because that is the only place the interplay can fail: the
app's `dictConfig` has to win over uvicorn's (which runs first), and uvicorn
has to write its access line inside the request, while `request_id_ctx` is
still set. A mock of either would stay green however a future uvicorn behaved.
"""

import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.core.logging import resolve_level
from tests.servers import free_port

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_BUDGET = 15  # seconds for the process to report it is up
LINE_BUDGET = 5  # seconds for a line to reach the log file


@pytest.mark.parametrize(
    ("log_level", "debug", "expected"),
    [(None, True, "DEBUG"), (None, False, "INFO"), ("WARNING", True, "WARNING")],
)
def test_the_level_follows_debug_unless_log_level_is_set(
    log_level: str | None, debug: bool, expected: str
) -> None:
    assert resolve_level(log_level, debug) == expected


def wait_for_line(path: Path, needle: str, timeout: float = LINE_BUDGET) -> str:
    """The log text once it contains `needle`; fails with that text on timeout."""
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        text = path.read_text()
        if needle in text:
            return text
        time.sleep(0.05)
    pytest.fail(f"{needle!r} never appeared in {path.name}:\n{text}")


class ServerLog:
    def __init__(self, port: int, stdout: Path, stderr: Path) -> None:
        self.url = f"http://127.0.0.1:{port}"
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(scope="module")
def server_log(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerLog]:
    """A real uvicorn serving the app, its output captured to files.

    Run from an empty directory with an environment built from scratch, so no
    dotenv file and nothing from the developer's shell leaks in. The database
    sits at a closed port: a request that needs it is refused with a 503,
    logged inside the request — the in-request line these tests look for.
    """
    workdir = tmp_path_factory.mktemp("server-log")
    port = free_port()
    log = ServerLog(port, workdir / "stdout.log", workdir / "stderr.log")
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(PROJECT_ROOT),
        "PYTHONUNBUFFERED": "1",
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "JWT_SECRET_KEY": "x" * 32,
        "DATABASE_URL": f"postgresql+asyncpg://u:p@127.0.0.1:{free_port()}/none",
    }
    with log.stdout.open("w") as out, log.stderr.open("w") as err:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=workdir,
            env=env,
            stdout=out,
            stderr=err,
        )
        try:
            try:
                wait_for_line(log.stdout, "Application startup complete", START_BUDGET)
            except pytest.fail.Exception:
                pytest.fail(f"uvicorn did not start:\n{log.stderr.read_text()}")
            yield log
        finally:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()


def test_server_and_app_lines_share_one_format_on_stdout(server_log: ServerLog) -> None:
    stamp = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO     \[-\]"
    stdout = server_log.stdout.read_text()

    assert re.search(rf"^{stamp} app\.main: Starting TaskHub API \(test\)$", stdout, re.M)
    assert re.search(rf"^{stamp} uvicorn\.error: Application startup complete\.$", stdout, re.M)
    # uvicorn's own handler is gone: nothing is left in its default format on stderr.
    assert not re.search(r"^INFO:", server_log.stderr.read_text(), re.M)


def test_every_line_written_during_a_request_carries_its_id(server_log: ServerLog) -> None:
    response = httpx.get(
        f"{server_log.url}/api/v1/projects", headers={"X-Request-ID": "trace-log-1"}
    )
    assert response.status_code == 503

    stdout = wait_for_line(server_log.stdout, "[trace-log-1] uvicorn.access:")
    lines = stdout.splitlines()
    assert any("[trace-log-1] app.core.handlers: Dependency unreachable" in line for line in lines)
    assert any("[trace-log-1] uvicorn.access:" in line and line.endswith(" 503") for line in lines)
