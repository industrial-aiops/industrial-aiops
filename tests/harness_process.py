"""Launch a protocol-harness subprocess and wait for its ``READY`` line.

Shared by the MC / S7 / EtherNet/IP / SECS-GEM live fixtures. Two things it fixes,
both found by a code review of the first versions:

**A crashed harness must not become a green skip.** Each fixture used to
``pytest.skip`` when the child died before printing READY — with its stderr sent to
``DEVNULL``, so there was nothing to look at. For the stdlib-only harnesses that is
wrong: an early exit there is a *harness regression*, not a missing dependency, and
skipping would turn ~30 tests into skips while CI stayed green. A syntax error in
``s7_plc_harness.py`` would have been invisible. Those now **fail**, with the
child's stderr in the message. Only a harness whose failure is genuinely
environmental (secsgem, whose library can fail to enable for host reasons) passes
``skip_on_exit=True``.

**The deadline has to be enforced while blocked, not between reads.** The old loop
was ``while time.monotonic() < deadline: proc.stdout.readline()`` — ``readline()``
blocks with no timeout, so a child that stayed alive but silent hung the session
instead of timing out. ``selectors`` waits on the pipe with a real timeout.
"""

from __future__ import annotations

import selectors
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest


@contextmanager
def harness(
    script: Path,
    port: int,
    *,
    args: tuple[str, ...] = (),
    timeout_s: float = 20.0,
    skip_on_exit: bool = False,
) -> Iterator[subprocess.Popen[str]]:
    """Run ``script <port> [args…]``, yield once it prints READY, kill it after.

    Args:
        script: the harness module to run.
        port: the port to pass it.
        args: extra argv for the harness — e.g. the EtherNet/IP one takes
            ``--micro800`` to answer with a Micro800 catalog number, which is
            what makes pycomm3 take its Micro800 code path.
        timeout_s: how long to wait for READY.
        skip_on_exit: skip rather than fail when the child EXITS early. Only for
            harnesses whose startup can fail for environmental reasons — and only
            for that branch: a child that is alive but silent past the deadline
            is a hang, and hangs are always failures.
    """
    # stderr goes to a FILE, not a pipe. A pipe nobody drains fills at ~64 KiB and
    # then blocks the child mid-write: `socketserver.ThreadingTCPServer` prints a
    # full traceback for every unhandled handler exception, so a harness that hits
    # a bad frame would stop replying and the test would fail as a client timeout,
    # with the explanation sitting unread in the pipe. A file cannot back up, and
    # the failure path still gets to read it.
    errors = tempfile.TemporaryFile(mode="w+")
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(script), str(port), *args],
        stdout=subprocess.PIPE,
        stderr=errors,
        text=True,
    )
    try:
        _wait_for_ready(proc, script, errors, timeout_s=timeout_s, skip_on_exit=skip_on_exit)
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)
        if proc.stdout is not None:
            proc.stdout.close()
        errors.close()


def _wait_for_ready(
    proc: subprocess.Popen[str],
    script: Path,
    errors: Any,
    *,
    timeout_s: float,
    skip_on_exit: bool,
) -> None:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _fail(proc, script, errors, f"did not print READY within {timeout_s:g}s", False)
            if not selector.select(timeout=min(remaining, 0.5)):
                if proc.poll() is not None:
                    _fail(proc, script, errors, "exited before printing READY", skip_on_exit)
                continue
            line = proc.stdout.readline()
            if not line:  # EOF — the child closed stdout or died
                _fail(proc, script, errors, "closed stdout before printing READY", skip_on_exit)
            if line.strip() == "READY":
                return
    finally:
        selector.close()


def _fail(
    proc: subprocess.Popen[str], script: Path, errors: Any, what: str, skip_on_exit: bool
) -> None:  # -> NoReturn
    proc.kill()
    stderr = ""
    try:
        errors.seek(0)
        stderr = errors.read()[-2000:]
    except Exception:  # noqa: BLE001 — diagnostics must not mask the real failure
        stderr = "<stderr unreadable>"
    message = f"{script.name} {what}"
    if stderr.strip():
        message += f"\n--- harness stderr ---\n{stderr.strip()}"
    if skip_on_exit:
        pytest.skip(message)
    pytest.fail(message)
