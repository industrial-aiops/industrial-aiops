"""Live Mitsubishi MC round-trip — real pymcprotocol against a real socket.

``test_mc.py`` monkeypatches ``_build_mc_client``, so pymcprotocol never ran: the
3E frame assembly, the device encoding, the signed-word decode and the bit
unpacking were all assumed.

Here the connector's genuine ``Type3E`` client talks over TCP to
``tests/mc_plc_harness.py``. **Evidence level, stated plainly:** ``pymcprotocol``
ships no server, so the far end is written by us from the frame spec — unlike the
ten protocols that face a real third-party counterparty. Two things still make
this much more than a mock:

* pymcprotocol's **real parser** decodes every byte, so a wrong subheader, length
  field or status offset fails against the library rather than against a stub that
  agrees with whatever we produced;
* the harness **decodes the request**, so asking for D100 vs M0 vs the wrong
  offset returns different data. A mock cannot tell those apart.

If we misread the 3E spec, harness and expectations are wrong together. A physical
MELSEC CPU remains 待核实 either way.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("pymcprotocol", reason="pymcprotocol not installed — install iaiops[mc]")

# Bare module name, not ``tests.``: pytest puts this directory on sys.path, while
# the repo root is only there under ``python -m pytest``.
from mc_plc_harness import BITS, CPU_CODE, CPU_TYPE, WORDS  # noqa: E402

from iaiops.connectors.mc import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def plc() -> Iterator[TargetConfig]:
    """A 3E PLC in a child process. Function-scoped so a write test cannot leak
    seeded state into a read test — the harness's word bank is mutable by design,
    since that is what proves a write reached it."""
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(Path(__file__).with_name("mc_plc_harness.py")), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdout is not None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.skip("MC harness exited before signalling READY")
            if proc.stdout.readline().strip() == "READY":
                break
        else:  # pragma: no cover — only on a pathologically slow host
            pytest.skip("MC harness did not start within 20s")

        yield TargetConfig(name="mc-live", protocol="mc", host="127.0.0.1", port=port, plctype="Q")
    finally:
        proc.kill()
        proc.wait(timeout=10)


# ─── the reads, over a real 3E frame ─────────────────────────────────────────


def test_cpu_status_identifies_the_plc(plc: TargetConfig) -> None:
    """Command 0x0101 — the round-trip that proves the link and the framing."""
    out = ops.mc_cpu_status(plc)
    assert out["cpu_type"].strip() == CPU_TYPE
    assert out["cpu_code"] == f"{CPU_CODE:04X}" or int(str(out["cpu_code"]), 16) == CPU_CODE


def test_read_words_lands_on_the_requested_device(plc: TargetConfig) -> None:
    out = ops.mc_read_words(plc, headdevice="D100", count=3)
    assert out["words"] == [WORDS[100], WORDS[101], WORDS[102]]
    assert out["count"] == 3


def test_words_are_decoded_as_signed(plc: TargetConfig) -> None:
    """D101 is seeded negative. An unsigned decode would return 65529, which is a
    plausible-looking number — exactly the kind of wrong value a mock cannot catch
    and an operator would not question."""
    out = ops.mc_read_words(plc, headdevice="D101", count=1)
    assert out["words"] == [-7]


def test_read_words_at_a_different_offset(plc: TargetConfig) -> None:
    """Guards against an address that is ignored or off by one."""
    out = ops.mc_read_words(plc, headdevice="D10", count=2)
    assert out["words"] == [WORDS[10], WORDS[11]]


def test_read_bits_unpacks_two_per_byte(plc: TargetConfig) -> None:
    """3E packs bit units two to a byte, high nibble first. Get the nibble order
    wrong and every other bit is inverted — a bug that reads as noise on a plant
    floor rather than as an error."""
    count = 7
    out = ops.mc_read_bits(plc, headdevice="M0", count=count)
    assert out["bits"] == [BITS[i] for i in range(count)]


def test_read_many_reads_scattered_devices_in_one_request(plc: TargetConfig) -> None:
    out = ops.mc_read_many(plc, word_devices=["D5", "D100"], dword_devices=["D20"])
    assert [w["value"] for w in out["words"]] == [WORDS[5], WORDS[100]]
    expected_dword = ((WORDS[21] & 0xFFFF) << 16) | (WORDS[20] & 0xFFFF)
    assert out["dwords"][0]["value"] == expected_dword


# ─── the write, and its BEFORE capture ───────────────────────────────────────


def test_dry_run_write_does_not_reach_the_plc(plc: TargetConfig) -> None:
    """The default. A preview must change nothing on the device — verified by
    reading the register back, not by trusting the return value."""
    before = ops.mc_read_words(plc, headdevice="D150", count=1)["words"]
    out = ops.mc_write_words(plc, headdevice="D150", values=[999], dry_run=True)
    assert out.get("dry_run") is True
    assert ops.mc_read_words(plc, headdevice="D150", count=1)["words"] == before


def test_applied_write_reaches_the_plc_and_captures_the_before_value(
    plc: TargetConfig,
) -> None:
    """The undo contract, end to end: the value the connector reports as ``before``
    must be what the device actually held, because that is what an operator would
    replay to roll back."""
    original = ops.mc_read_words(plc, headdevice="D150", count=2)["words"]

    out = ops.mc_write_words(plc, headdevice="D150", values=[111, 222], dry_run=False)
    assert out.get("applied") is True

    assert ops.mc_read_words(plc, headdevice="D150", count=2)["words"] == [111, 222]
    assert out.get("before") == original, (
        f"the captured BEFORE ({out.get('before')}) is not what the PLC held ({original}) "
        "— an undo built from it would restore the wrong value"
    )


# ─── honesty ─────────────────────────────────────────────────────────────────


def test_an_unsupported_device_teaches_rather_than_fabricating(plc: TargetConfig) -> None:
    """The harness answers 0xC059 for a device it does not serve, as a real CPU
    does for a request it cannot honour. That must surface as an error, never as
    zeros an operator could read as real measurements."""
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 — pymcprotocol's own type
        ops.mc_read_words(plc, headdevice="W0", count=2)
    assert str(excinfo.value).strip(), "the failure carried no message"
