"""The one sweep verdict a laptop cannot fake: a genuine silently-dropped port.

``refused`` and ``filtered`` are the two findings this scanner refuses to merge —
a refused port proves the host is ALIVE and simply runs no industrial service,
while a filtered one usually means an ACL between here and it. Everywhere else
the timeout path is driven by a stub that raises ``TimeoutError`` because the
test told it to, which proves the branch is wired, not that the kernel behaves
that way.

A real silent drop needs a firewall rule. This runs one inside a container's own
network namespace (``--cap-add=NET_ADMIN``), probes only that container's
loopback, and asserts all three verdicts at once. Nothing outside the container
is contacted.

Skipped when Docker is unavailable, which is most laptops — the point is that CI
and anyone with a container runtime gets the real check rather than a comment
promising it was done once.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

_IMAGE = "python:3.12-slim"

_PROBE = textwrap.dedent(
    """
    import socket, subprocess, sys, threading, time
    sys.path.insert(0, "/work")
    from iaiops.core.discovery.sweep import probe_port
    from iaiops.core.discovery.types import PORT_FILTERED, PORT_OPEN, PORT_REFUSED

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 9001)); srv.listen(8)

    def serve():
        while True:
            try:
                srv.accept()[0].close()
            except OSError:
                break

    threading.Thread(target=serve, daemon=True).start()
    subprocess.run(
        ["iptables", "-A", "INPUT", "-p", "tcp", "--dport", "9003", "-j", "DROP"], check=True
    )

    results = {}
    for port in (9001, 9002, 9003):
        started = time.monotonic()
        out = probe_port("127.0.0.1", port, timeout_s=2.0)
        results[port] = (out.state, out.proves_host_alive, round(time.monotonic() - started, 2))

    assert results[9001][0] == PORT_OPEN, results
    assert results[9002][0] == PORT_REFUSED, results
    assert results[9003][0] == PORT_FILTERED, results
    # The distinction that matters: refused proves the host is there, a silent
    # drop proves nothing at all.
    assert results[9002][1] is True, results
    assert results[9003][1] is False, results
    # And a dropped packet really does burn the whole timeout.
    assert results[9003][2] >= 1.8, results
    print("VERDICTS_OK", results)
    """
)


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(
    not _docker_available(), reason="docker unavailable — needs a container runtime"
)
def test_three_port_verdicts_against_a_real_firewall_rule(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    (tmp_path / "probe.py").write_text(_PROBE, encoding="utf-8")

    script = (
        "set -e\n"
        "apt-get -qq update >/dev/null 2>&1\n"
        "DEBIAN_FRONTEND=noninteractive apt-get -qq install -y iptables >/dev/null 2>&1\n"
        "command -v iptables >/dev/null || { echo NO_IPTABLES; exit 2; }\n"
        "python3 /probe/probe.py\n"
    )
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "-v",
            f"{repo_root}:/work:ro",
            "-v",
            f"{tmp_path}:/probe:ro",
            _IMAGE,
            "sh",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == 2 or "NO_IPTABLES" in output:
        pytest.skip("could not install iptables in the container (no network?)")
    assert proc.returncode == 0, output
    assert "VERDICTS_OK" in output, output
