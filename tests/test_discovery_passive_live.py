"""The L0 claim a laptop cannot check: an ARP entry for a host that never replied.

Everywhere else the incomplete-entry filter is driven from a fixture whose flags
field says ``0x0`` because the fixture says so. That proves the branch is wired,
not that a real kernel writes such a row or that this parser recognises the row
it actually writes.

Here an ARP request is genuinely sent and genuinely unanswered. It goes to an
unused address on the container's OWN docker-bridge subnet, so the request never
leaves that bridge — nothing on the host's network is contacted. The kernel then
holds a real incomplete entry, and the assertion is that it does not become a
device in an inventory.

Skipped without a container runtime, which is most laptops. The point is that CI
gets the real check instead of a comment promising someone once did it by hand.
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
    import sys
    sys.path.insert(0, "/work")
    from iaiops.core.discovery.passive import read_arp_table

    raw = open("/proc/net/arp").read()
    rows = [ln.split() for ln in raw.splitlines()[1:] if len(ln.split()) >= 6]
    # Flag bit 0x2 is ATF_COM — set once the entry is complete. Anything without
    # it is a request that went out and was never answered.
    incomplete = [r[0] for r in rows if int(r[2], 16) & 0x2 == 0]
    complete = [r[0] for r in rows if int(r[2], 16) & 0x2]

    entries, notes = read_arp_table()
    found = {e.ip for e in entries}

    assert incomplete, "no unanswered ARP was produced — this test proved nothing"
    assert notes == (), notes
    assert not set(incomplete) & found, (incomplete, found)
    # The complement matters just as much: the filter must not be discarding
    # everything and passing by accident.
    assert set(complete) & found, (complete, found)
    for entry in entries:
        assert int(entry.mac.split(":")[0], 16) & 0x01 == 0, entry
        assert entry.interface, entry
    print("ARP_OK", {"incomplete": incomplete, "reported": sorted(found)})
    """
)


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(
    not _docker_available(), reason="docker unavailable — needs a container runtime"
)
def test_an_unanswered_arp_is_not_reported_as_a_device(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    (tmp_path / "probe.py").write_text(_PROBE, encoding="utf-8")

    script = (
        "set -e\n"
        "apt-get -qq update >/dev/null 2>&1\n"
        "DEBIAN_FRONTEND=noninteractive apt-get -qq install -y "
        "iputils-ping iproute2 >/dev/null 2>&1\n"
        "command -v ping >/dev/null || { echo NO_PING; exit 2; }\n"
        # An unused address on the container's own bridge subnet. The ARP request
        # is broadcast on that bridge and nowhere else.
        "BASE=$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1 | cut -d. -f1-3)\n"
        'ping -c1 -W1 "$BASE.251" >/dev/null 2>&1 || true\n'
        "python3 /probe/probe.py\n"
    )
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
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
    if proc.returncode == 2 or "NO_PING" in output:
        pytest.skip("could not install ping/iproute2 in the container (no network?)")
    assert proc.returncode == 0, output
    assert "ARP_OK" in output, output
