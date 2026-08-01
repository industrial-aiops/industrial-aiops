"""Live S7comm round-trip — real pyS7 over a real ISO-TSAP socket.

``test_s7.py`` monkeypatches ``_build_s7_client``, so ``pyS7`` never ran. That is
a lot of unexercised protocol: the COTP connection request, the PDU-size
negotiation, the S7ANY address encoding (area code, DB number, and a **bit**
address — S7 addresses are in bits, so ``start * 8 + bit_offset``), and the
per-item response parsing with its return codes and fill bytes.

**Evidence level, same caveat as the MC live test.** ``pyS7`` ships no server, so
``tests/s7_plc_harness.py`` is written by us from the frame layout rather than
being an independent implementation; misread the spec and harness and expectations
are wrong together. What it still buys over a mock: pyS7's **real parser** checks
every response (TPKT version and length, COTP length, S7 header, per-item return
codes), and the harness **decodes the request**, so DB number, area and byte
offset all select what comes back. A physical S7 CPU stays 待核实.

Two of the harness's own bugs, found by this very asymmetry and worth recording:
the first version read the request's parameter at the *response* offset (19 rather
than 17 — an ACK_DATA header carries an error class/code that a job header does
not), and then mis-indexed the 12-byte item spec by one. Both showed up as pyS7
rejecting the answer, which is exactly the check a mock cannot perform.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("pyS7", reason="pyS7 not installed — install iaiops[s7]")

# Bare module name, not ``tests.``: pytest puts this directory on sys.path, while
# the repo root is only there under ``python -m pytest``.
from harness_process import harness  # noqa: E402
from s7_plc_harness import DB1, DB2, MERKER  # noqa: E402

from iaiops.connectors.s7 import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def plc() -> Iterator[TargetConfig]:
    """An S7 PLC in a child process. Function-scoped so the write test cannot leak
    mutated DB contents into a read test."""
    port = _free_port()
    with harness(Path(__file__).with_name("s7_plc_harness.py"), port):
        yield TargetConfig(
            name="s7-live", protocol="s7", host="127.0.0.1", port=port, rack=0, slot=1
        )


# ─── reads, over a real COTP + S7 exchange ───────────────────────────────────


def test_read_db_int(plc: TargetConfig) -> None:
    """Proves the whole chain: COTP connect, PDU negotiation, Read Var, parse."""
    out = ops.s7_read_db(plc, db=1, dtype="INT", start=0, count=1)
    assert out["items"][0]["value"] == 4242
    assert out["items"][0]["address"] == "DB1,INT0"


def test_int_is_decoded_as_signed(plc: TargetConfig) -> None:
    """DB1.DBW2 holds -7. An unsigned decode returns 65529 — a plausible-looking
    number that a mock cannot catch and an operator would not question."""
    out = ops.s7_read_db(plc, db=1, dtype="INT", start=2, count=1)
    assert out["items"][0]["value"] == -7


def test_real_is_decoded_big_endian(plc: TargetConfig) -> None:
    """S7 is big-endian. Byte-swapped, 42.5 decodes to a wildly different float."""
    out = ops.s7_read_db(plc, db=1, dtype="REAL", start=4, count=1)
    assert out["items"][0]["value"] == pytest.approx(42.5)


def test_read_lands_on_the_requested_db(plc: TargetConfig) -> None:
    """DB1 and DB2 hold different ramps, so reading the wrong block is visible."""
    out = ops.s7_read_many(plc, ["DB1,INT0", "DB2,INT0"])
    values = [item["value"] for item in out["items"]]
    assert values == [4242, 9000]


def test_read_at_a_non_zero_offset(plc: TargetConfig) -> None:
    """Guards against an address that is ignored or off by one — S7 addresses go
    on the wire in BITS (``start * 8``), so an offset bug here is easy to make."""
    out = ops.s7_read_db(plc, db=1, dtype="INT", start=10, count=1)
    assert out["items"][0]["value"] == 1000


def test_word_and_dword_widths_are_right(plc: TargetConfig) -> None:
    """The regression a code review caught, now pinned.

    The harness's width table originally mapped WORD to 1 byte and DWORD to 2. A
    WORD read of the seeded 4242 came back as **4096** — silently wrong, no error —
    and DWORD raised "payload too short". Neither was noticed because the tests only
    used INT / REAL / BIT, and the connector exposes all of these as first-class
    dtypes. Widths now come from pyS7's own ``DataTypeSize``.
    """
    assert ops.s7_read_db(plc, db=1, dtype="WORD", start=0, count=1)["items"][0]["value"] == 4242
    # bytes 0..3 = 0x10 0x92 0xFF 0xF9 → 4242 then -7, read together as one DINT.
    expected = int.from_bytes(bytes(DB1[0:4]), "big")
    assert (
        ops.s7_read_db(plc, db=1, dtype="DWORD", start=0, count=1)["items"][0]["value"] == expected
    )
    assert (
        ops.s7_read_db(plc, db=1, dtype="DINT", start=0, count=1)["items"][0]["value"] == expected
    )


def test_lreal_decodes_correctly_despite_the_ambiguous_transport(plc: TargetConfig) -> None:
    """pyS7 sends transport ``0x04`` for **WORD with an element count** and also for
    **LREAL / STRING / WSTRING with a byte count** — one code, two meanings, and
    nothing on the wire distinguishes them.

    A review flagged that as unresolvable, and strictly it is; but the consequence
    is benign in one direction and only one. Resolving it as WORD makes an LREAL
    request **over**-read (8 → 16 bytes) and pyS7 takes only the 8 it needs, so the
    value is right. **Under**-reading is what corrupts data — which is exactly what
    the old width table did to WORD.

    Asserted rather than reasoned about, because "it should be fine" is how the
    WORD bug survived.
    """
    expected = struct.unpack(">d", bytes(DB1[0:8]))[0]
    out = ops.s7_read_db(plc, db=1, dtype="LREAL", start=0, count=1)
    assert out["items"][0]["value"] == expected


def test_bit_addresses_select_the_right_bit(plc: TargetConfig) -> None:
    """DB1.DBB8 is 0xA5 = 1010_0101: bit 0 set, bit 1 clear, bit 2 set.

    What this actually proves, measured rather than assumed: pyS7 **coalesces**
    the three bit tags into a single byte read (transport 0x02, address 64 bits =
    byte 8) and extracts the bits itself. So this pins the connector's address
    construction — the right byte is requested — plus pyS7's extraction. It does
    NOT exercise the harness's single-bit branch, which mutation testing showed is
    dead on this path; that is noted there rather than left to look covered.

    The assertion still discriminates the failure that matters: if anything
    returned the byte as a whole, bit 1 would read True instead of False."""
    out = ops.s7_read_many(plc, ["DB1,X8.0", "DB1,X8.1", "DB1,X8.2"])
    assert [item["value"] for item in out["items"]] == [True, False, True]


def test_reads_the_merker_area_not_just_data_blocks(plc: TargetConfig) -> None:
    """A different area code (0x83 vs 0x84) — the connector must send the right one."""
    out = ops.s7_read_many(plc, ["M0.0"])
    assert out["items"][0]["value"] is bool(MERKER[0] & 0x01)


# ─── the write, and its BEFORE capture ───────────────────────────────────────


def test_dry_run_write_does_not_reach_the_plc(plc: TargetConfig) -> None:
    """Verified by reading the DB word back, not by trusting the return value."""
    before = ops.s7_read_db(plc, db=1, dtype="INT", start=20, count=1)["items"][0]["value"]
    out = ops.s7_write_db(plc, db=1, dtype="INT", start=20, value=555, dry_run=True)
    assert out["dry_run"] is True
    after = ops.s7_read_db(plc, db=1, dtype="INT", start=20, count=1)["items"][0]["value"]
    assert after == before


def test_applied_write_reaches_the_plc_and_captures_the_before_value(
    plc: TargetConfig,
) -> None:
    """The undo contract end to end: the reported ``before`` must be what the CPU
    actually held, because that is what an operator would replay to roll back."""
    original = ops.s7_read_db(plc, db=1, dtype="INT", start=20, count=1)["items"][0]["value"]

    out = ops.s7_write_db(plc, db=1, dtype="INT", start=20, value=555, dry_run=False)
    assert out["applied"] is True

    after = ops.s7_read_db(plc, db=1, dtype="INT", start=20, count=1)["items"][0]["value"]
    assert after == 555, "the write did not reach the data block"
    assert out["before"] == original, (
        f"the captured BEFORE ({out['before']}) is not what the CPU held ({original}) "
        "— an undo built from it would restore the wrong value"
    )


# ─── honesty ─────────────────────────────────────────────────────────────────


def test_a_missing_data_block_teaches_rather_than_fabricating(plc: TargetConfig) -> None:
    """The harness answers OUT_OF_RANGE for a DB it does not hold, as a real CPU
    does. That must surface as an actionable error, never as a zero an operator
    could read as a real value."""
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 — pyS7 / connector types
        ops.s7_read_db(plc, db=99, dtype="INT", start=0, count=1)

    message = str(excinfo.value)
    assert message.strip(), "the failure carried no message"
    assert "OUT_OF_RANGE" in message or "rack" in message, (
        f"the error does not help the operator: {message!r}"
    )


@pytest.mark.unit
def test_the_seeded_banks_differ_where_the_tests_read() -> None:
    """Guards the read assertions from passing vacuously: if DB1 and DB2 held the
    same bytes, 'read the right block' and 'read the wrong block' would agree."""
    assert DB1[0:2] != DB2[0:2]
    assert DB1[10:12] != DB2[10:12]
