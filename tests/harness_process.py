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
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def harness(
    script: Path, port: int, *, timeout_s: float = 20.0, skip_on_exit: bool = False
) -> Iterator[subprocess.Popen[str]]:
    """Run ``script <port>``, yield once it prints READY, and kill it afterwards.

    Args:
        script: the harness module to run.
        port: the port to pass it.
        timeout_s: how long to wait for READY.
        skip_on_exit: skip rather than fail when the child exits early. Only for
            harnesses whose startup can fail for environmental reasons.
    """
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(script), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_ready(proc, script, timeout_s=timeout_s, skip_on_exit=skip_on_exit)
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _wait_for_ready(
    proc: subprocess.Popen[str], script: Path, *, timeout_s: float, skip_on_exit: bool
) -> None:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _fail(proc, script, f"did not print READY within {timeout_s:g}s", skip_on_exit)
            if not selector.select(timeout=min(remaining, 0.5)):
                if proc.poll() is not None:
                    _fail(proc, script, "exited before printing READY", skip_on_exit)
                continue
            line = proc.stdout.readline()
            if not line:  # EOF — the child closed stdout or died
                _fail(proc, script, "closed stdout before printing READY", skip_on_exit)
            if line.strip() == "READY":
                return
    finally:
        selector.close()


def _fail(
    proc: subprocess.Popen[str], script: Path, what: str, skip_on_exit: bool
) -> None:  # -> NoReturn
    proc.kill()
    stderr = ""
    if proc.stderr is not None:
        try:
            stderr = proc.stderr.read()[-2000:]
        except Exception:  # noqa: BLE001 — diagnostics must not mask the real failure
            stderr = "<stderr unreadable>"
    message = f"{script.name} {what}"
    if stderr.strip():
        message += f"\n--- harness stderr ---\n{stderr.strip()}"
    if skip_on_exit:
        pytest.skip(message)
    pytest.fail(message)
