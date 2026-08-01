"""Live EtherNet/IP round-trip — real pycomm3 over a real CIP session.

``test_eip.py`` monkeypatches ``_build_eip_client``, so ``pycomm3`` never ran —
and for this protocol that is the largest gap of any connector here, because
``LogixDriver.open()`` alone performs a five-step session dance before a single
tag is read: RegisterSession, ListIdentity, Forward Open, controller-info upload,
and a full **tag-list enumeration** off the Symbol object.

**Evidence level, same caveat as the MC and S7 live tests.** ``pycomm3`` ships no
server, so ``tests/eip_plc_harness.py`` is written by us from the EtherNet/IP
encapsulation and CIP layouts; misread them and harness and expectations are wrong
together. What it buys: pycomm3's **real driver** drives the whole session and
parses every reply, and the harness **decodes the request** — the ANSI symbolic
segment names the tag, so a different tag returns different data. A physical
ControlLogix stays 待核实.

Building the harness surfaced how much of this the driver actually requires, each
step found by the real client rejecting the previous answer:

* a CPF reply missing its **item-count** field shifted everything by two bytes,
  which pycomm3 reported as ``Error packing -128 as USINT`` — it had read the
  service byte from the wrong offset;
* refusing **Forward Open** is not a shortcut: the driver falls back to a standard
  Forward Open and then fails, so connected messaging (``SendUnitData``) has to be
  served too;
* a multi-tag read is not N reads — it becomes one **Multiple Service Packet**
  (service ``0x0A``) carrying N embedded requests, and needs the matching reply
  shape.

None of that is reachable through a mock.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("pycomm3", reason="pycomm3 not installed — install iaiops[eip]")

# Bare module name, not ``tests.``: pytest puts this directory on sys.path, while
# the repo root is only there under ``python -m pytest``.
from eip_plc_harness import PRODUCT_NAME, TAGS  # noqa: E402

from iaiops.connectors.eip import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def plc() -> Iterator[TargetConfig]:
    """A CIP PLC in a child process. Function-scoped so the write test cannot leak
    a mutated tag value into a read test — the harness's tag bank is mutable by
    design, since that is what proves a write reached it."""
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(Path(__file__).with_name("eip_plc_harness.py")), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdout is not None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.skip("EtherNet/IP harness exited before signalling READY")
            if proc.stdout.readline().strip() == "READY":
                break
        else:  # pragma: no cover — only on a pathologically slow host
            pytest.skip("EtherNet/IP harness did not start within 20s")

        yield TargetConfig(
            name="eip-live",
            protocol="ethernetip",
            host=f"127.0.0.1:{port}",
            plctype="logix",
            timeout_s=5,
        )
    finally:
        proc.kill()
        proc.wait(timeout=10)


# ─── the session, and what it uploads ────────────────────────────────────────


def test_controller_info_completes_the_whole_session(plc: TargetConfig) -> None:
    """Register session → list identity → forward open → controller info. Any one
    of those failing takes the whole connector down, and none of them ran before."""
    out = ops.eip_controller_info(plc)
    assert out["controller"]["product_name"] == PRODUCT_NAME
    assert out["controller"]["vendor"].startswith("Rockwell")


def test_tag_list_upload_returns_the_controller_tags(plc: TargetConfig) -> None:
    """``LogixDriver.open()`` enumerates the Symbol object before anything else
    works. This is the step whose absence made every op fail with 'failed to get
    attribute list' while the session itself was already fine."""
    out = ops.eip_list_tags(plc)
    names = {tag["name"] for tag in out["tags"]}
    assert names == set(TAGS)
    by_name = {tag["name"]: tag for tag in out["tags"]}
    assert by_name["MotorSpeed"]["data_type"] == "DINT"
    assert by_name["Temperature"]["data_type"] == "REAL"


# ─── reads, over real CIP ────────────────────────────────────────────────────


def test_read_tag_returns_the_seeded_value(plc: TargetConfig) -> None:
    out = ops.eip_read_tag(plc, "MotorSpeed")
    assert out["good"] is True
    assert out["value"] == 1750
    assert out["type"] == "DINT"


def test_read_lands_on_the_requested_tag(plc: TargetConfig) -> None:
    """The tag rides in an ANSI symbolic segment. A harness that ignored it — or a
    connector that sent the wrong name — would return the wrong tag's value."""
    assert ops.eip_read_tag(plc, "Setpoint")["value"] == 4242
    assert ops.eip_read_tag(plc, "MotorSpeed")["value"] == 1750


def test_read_many_uses_one_multiple_service_packet(plc: TargetConfig) -> None:
    """A multi-tag read is not N reads: pycomm3 packs them into a single service
    0x0A request. Mixed types in one packet also pin the per-item type decoding."""
    out = ops.eip_read_many(plc, ["Setpoint", "Offset", "Temperature"])
    values = {item["tag"]: item["value"] for item in out["items"]}
    assert values["Setpoint"] == 4242
    assert values["Offset"] == -7, "an unsigned decode would give 65529"
    assert values["Temperature"] == pytest.approx(42.5)
    assert all(item["good"] for item in out["items"])


# ─── the write, and its BEFORE capture ───────────────────────────────────────


def test_dry_run_write_does_not_reach_the_plc(plc: TargetConfig) -> None:
    """Verified by reading the tag back, not by trusting the return value."""
    out = ops.eip_write_tag(plc, tag="Setpoint", value=99, dry_run=True)
    assert out["dry_run"] is True
    assert ops.eip_read_tag(plc, "Setpoint")["value"] == 4242


def test_applied_write_reaches_the_plc_and_captures_the_before_value(
    plc: TargetConfig,
) -> None:
    """The undo contract end to end: the reported ``before`` must be what the
    controller actually held, because that is what an operator replays to roll
    back."""
    original = ops.eip_read_tag(plc, "Setpoint")["value"]

    out = ops.eip_write_tag(plc, tag="Setpoint", value=99, dry_run=False)
    assert out["applied"] is True

    assert ops.eip_read_tag(plc, "Setpoint")["value"] == 99, "the write did not land"
    assert out["before"] == original, (
        f"the captured BEFORE ({out['before']}) is not what the controller held "
        f"({original}) — an undo built from it would restore the wrong value"
    )


# ─── honesty ─────────────────────────────────────────────────────────────────


def test_a_missing_tag_teaches_rather_than_fabricating(plc: TargetConfig) -> None:
    """The harness answers CIP status 0x05 for a tag it does not hold, as a real
    controller does. The connector must report that as not-good with a message —
    never as a value an operator could act on."""
    out = ops.eip_read_tag(plc, "NoSuchTag")
    assert out["good"] is False
    assert out["value"] is None, "a missing tag produced a value"
    assert "NoSuchTag" in out["error"] or "exist" in out["error"].lower()


@pytest.mark.unit
def test_the_seeded_tags_differ_from_each_other() -> None:
    """Guards the read assertions from passing vacuously: if every tag held the
    same value, 'read the right tag' and 'read the wrong tag' would agree."""
    values = [value for _cip_type, value in TAGS.values()]
    assert len(set(map(str, values))) == len(values)
