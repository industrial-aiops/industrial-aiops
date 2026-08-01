"""Live SECS/GEM round-trip against a REAL secsgem equipment — no fab tool.

``test_secsgem.py`` monkeypatches the host handler, so nothing below it ran: the
HSMS connect / select handshake, the SECS-II encoding of each request, and the
decoding of each reply were all assumed.

Here a real ``GemEquipmentHandler`` listens in HSMS **PASSIVE** mode on loopback
and the connector's real ``GemHostHandler`` connects to it in ACTIVE mode, so
every message below goes over a socket and through both libraries' codecs:

  S1F1/F2 are-you-there · S1F11/F12 SV namelist · S1F3/F4 SV values ·
  S2F29/F30 EC namelist · S2F13/F14 EC values · S5F5/F6 alarm list

The equipment is seeded with custom SVs / ECs / alarms so the assertions are
about *our* values rather than secsgem's built-ins, which would pass even if the
request never named anything.

**This is how the S7F19 defect below was found.** ``GemEquipmentHandler`` does not
implement S7F19 — like many real tools, since process-program transfer is an
OPTIONAL GEM capability — and against a mock that always answers, that path had
never been exercised.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("secsgem", reason="secsgem not installed — install iaiops[secsgem]")

from harness_process import harness  # noqa: E402

from iaiops.connectors.secsgem import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]

# One source of truth for what the harness seeded. Imported by BARE module name,
# not ``tests.``: pytest puts this directory on sys.path, whereas the repo root is
# only there under ``python -m pytest`` (which inserts CWD). CI runs plain
# ``pytest``, where the dotted form raises ModuleNotFoundError.
from secsgem_equipment_harness import (  # noqa: E402
    ALARM_CODE as _ALARM_CODE,
)
from secsgem_equipment_harness import (  # noqa: E402
    ALARM_TEXT as _ALARM_TEXT,
)
from secsgem_equipment_harness import (  # noqa: E402
    ALID as _ALID,
)
from secsgem_equipment_harness import (  # noqa: E402
    EC_VALUE as _EC_VALUE,
)
from secsgem_equipment_harness import (  # noqa: E402
    ECID as _ECID,
)
from secsgem_equipment_harness import (  # noqa: E402
    SV_VALUE as _SV_VALUE,
)
from secsgem_equipment_harness import (  # noqa: E402
    SVID as _SVID,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def equipment() -> Iterator[TargetConfig]:
    """A real secsgem equipment in a CHILD PROCESS, seeded with known SV/EC/alarm.

    **The process boundary is a finding, not a style choice.** ``GemEquipmentHandler``
    does not survive repeated lifecycle in one interpreter:

    * sharing one handler across tests failed non-deterministically — a different
      test each run — with the equipment logging ``WrongSourceStateError: Invalid
      source state for transition 'select': COMMUNICATING (expected
      NOT_COMMUNICATING)``. It had not returned to NOT_COMMUNICATING before the next
      ACTIVE connect landed, so the select failed and the host timed out;
    * building a fresh handler per test instead **hung the interpreter** on teardown.

    So the equipment gets its own process, killed at the end — the same shape the
    energy repo's DNP3 live test uses, for the same reason.

    待核实 whether real fab equipment shows the reconnect behaviour. HSMS has a T7
    "not-selected" timer precisely because a tool needs time to clean up a dropped
    selection, so it is plausible; it is equally plausible this is specific to
    secsgem. **Not asserted either way** — the process boundary removes the variable
    so the SECS-II assertions test what they claim to, and the observation is
    written down rather than papered over.
    """
    port = _free_port()
    # skip_on_exit: unlike the stdlib-only harnesses, this one can fail to start for
    # environmental reasons (secsgem import / enable), which is not a regression.
    with harness(
        Path(__file__).with_name("secsgem_equipment_harness.py"),
        port,
        timeout_s=30,
        skip_on_exit=True,
    ):
        yield TargetConfig(
            name="secsgem-live", protocol="secsgem", host="127.0.0.1", port=port, unit_id=0
        )


def _find(rows: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any] | None:
    return next((r for r in rows if isinstance(r, dict) and r.get(key) == value), None)


# ─── the HSMS link itself ────────────────────────────────────────────────────


def test_host_establishes_the_hsms_link(equipment: TargetConfig) -> None:
    """Connect, select, S1F1 — the handshake the mock never performed."""
    out = ops.equipment_status(equipment)
    assert "COMMUNICATING" in out["communication_state"]
    assert out["are_you_there"], "no S1F2 came back"


# ─── SECS-II reads, encoded and decoded for real ─────────────────────────────


def test_status_variable_namelist_includes_the_seeded_one(equipment: TargetConfig) -> None:
    out = ops.list_status_variables(equipment)
    row = _find(out["status_variables"], "SVID", _SVID)
    assert row is not None, f"SVID {_SVID} missing from the namelist: {out}"
    assert row["SVNAME"] == "ChamberTemp"
    assert row["UNITS"] == "degC"


def test_status_variable_value_round_trips(equipment: TargetConfig) -> None:
    """The seeded value must come back — not a default, not the built-ins."""
    out = ops.read_status_variables(equipment, [_SVID])
    assert out["values"] == [_SV_VALUE]


def test_equipment_constant_namelist_carries_min_max_default(equipment: TargetConfig) -> None:
    out = ops.list_equipment_constants(equipment)
    row = _find(out["equipment_constants"], "ECID", _ECID)
    assert row is not None, f"ECID {_ECID} missing: {out}"
    assert (row["ECMIN"], row["ECMAX"], row["ECDEF"]) == (0, 500, 300)


def test_equipment_constant_value_round_trips(equipment: TargetConfig) -> None:
    out = ops.read_equipment_constants(equipment, [_ECID])
    assert out["values"] == [_EC_VALUE]


def test_alarm_list_carries_id_severity_and_text(equipment: TargetConfig) -> None:
    out = ops.list_alarms(equipment)
    row = _find(out["alarms"], "ALID", _ALID)
    assert row is not None, f"ALID {_ALID} missing: {out}"
    assert row["ALTX"] == _ALARM_TEXT
    assert row["ALCD"] == _ALARM_CODE


# ─── honesty ─────────────────────────────────────────────────────────────────


def test_unknown_svid_does_not_fabricate_a_value(equipment: TargetConfig) -> None:
    """SEMI E5 answers an unknown SVID with a zero-length item. Whatever we render
    it as, it must not be a number an operator could mistake for a reading."""
    out = ops.read_status_variables(equipment, [424242])
    assert out.get("values") in ([[]], [None], []), (
        f"an unknown SVID produced something value-like: {out}"
    )


def test_unsupported_function_teaches_instead_of_returning_raw_bytes(
    equipment: TargetConfig,
) -> None:
    """The defect this file was written to find.

    ``GemEquipmentHandler`` does not implement S7F19 — process-program transfer is
    an OPTIONAL GEM capability that many real tools omit. secsgem then returns the
    **undecoded message bytes**, which ``_plain`` hex-encoded and the connector
    labelled ``process_programs``::

        {"count": null, "process_programs": "0000871300009e036f8a"}

    That blob is the echoed S7F19 request header. Not a fabricated value, but
    non-data under a data label — a model reading the tool result would report the
    equipment as having process programs. It must say what happened instead.
    """
    out = ops.list_process_programs(equipment)

    assert "error" in out, f"unsupported S7F19 was reported as data: {out}"
    assert "S7F19" in out["error"]
    assert out.get("hint"), "no hint for the operator"
    assert "process_programs" not in out, "raw bytes still presented under a data key"


def test_the_guard_does_not_fire_on_decoded_replies() -> None:
    """Guards the fix from over-reaching. A guard that turned every reply into an
    error would satisfy the test above while destroying the connector.

    Pure, and deliberately so: the five live reads above are already the end-to-end
    evidence that the working paths still return data — each asserts a real seeded
    value came back. Re-proving it by opening five more sessions in one test is what
    the fixture docstring warns about, and it did in fact fail that way.
    """
    for decoded in ([], [{"SVID": 1}], {"a": 1}, "text", 42, None, [[]]):
        assert ops._undecodable(decoded, what="x", stream_function="S1F1") is None, (
            f"the guard fired on a decoded reply: {decoded!r}"
        )

    for raw in (b"\x00\x00\x87\x13", bytearray(b"\x00")):
        err = ops._undecodable(raw, what="process-program directory", stream_function="S7F19")
        assert err is not None and "S7F19" in err["error"]
