"""Live EtherNet/IP for the two NON-Logix drivers: PCCC (SLC) and Micro800.

`test_eip_live.py` took the Logix path to rung 2b. The other two `plctype`
routes stayed mock-only, and they are not variations on Logix:

* **`slc`** is a different protocol inside the same encapsulation — CIP service
  0x4B carrying DF1/PCCC, numbered data files instead of a symbol table, and
  `pycomm3.SLCDriver` parsing replies at fixed byte offsets. `tests/eip_pccc_plc.py`
  answers it.
* **`micro800`** is `LogixDriver` again, but pycomm3 switches behaviour on the
  catalog number it reads out of ListIdentity: no multi-service packets, no
  unconnected sends, no program scope. Nothing about that is visible unless the
  far end *identifies* as a Micro800, so the harness can now do that on request.

Rung **2b**, like the Logix half: the far end is ours, the client is pycomm3.

What is still not covered: a physical SLC 5/05, MicroLogix or Micro820/850/870;
PLC-5-specific addressing; ST (string) and A (ASCII) files; a PCCC route bridged
through a ControlLogix backplane.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("pycomm3", reason="pycomm3 not installed — install iaiops[eip]")

# Bare module names, not ``tests.``: pytest puts this directory on sys.path.
from eip_pccc_plc import DATA_FILES, PROCESSOR_TYPE  # noqa: E402
from eip_plc_harness import MICRO800_PRODUCT_NAME  # noqa: E402
from harness_process import harness  # noqa: E402

from iaiops.connectors.eip import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]

_HARNESS = Path(__file__).with_name("eip_plc_harness.py")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _multiple_service_count(target: TargetConfig) -> int:
    """Ask the harness how many Multiple Service Packets it has served."""
    host, port = target.host.split(":")
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(struct.pack("<HHII", 0x0099, 0, 0, 0) + b"\x00" * 12)
        reply = sock.recv(64)
    return int(struct.unpack_from("<I", reply, 24)[0])


@pytest.fixture()
def slc() -> Iterator[TargetConfig]:
    """An SLC-500-flavoured PLC in a child process (function-scoped: writes mutate)."""
    port = _free_port()
    with harness(_HARNESS, port):
        yield TargetConfig(
            name="slc-live",
            protocol="ethernetip",
            host=f"127.0.0.1:{port}",
            plctype="slc",
            timeout_s=5,
        )


@pytest.fixture()
def micro800() -> Iterator[TargetConfig]:
    """The same harness, answering with a Micro800 catalog number."""
    port = _free_port()
    with harness(_HARNESS, port, args=("--micro800",)):
        yield TargetConfig(
            name="micro800-live",
            protocol="ethernetip",
            host=f"127.0.0.1:{port}",
            plctype="micro800",
            timeout_s=5,
        )


# ─── SLC / PCCC ──────────────────────────────────────────────────────────────


def test_slc_identity_comes_from_the_df1_diagnostic_command(slc: TargetConfig) -> None:
    """A PCCC controller has no Identity object — the processor type is a DF1 read.

    `get_plc_info()` (what the Logix path uses) does not exist here; the connector
    has to send CMD 0x06 / FNC 0x03 instead. Reading the type back off the wire is
    what proves it did, and that the driver selector actually routed to SLCDriver.
    """
    result = ops.eip_controller_info(slc)

    assert result["plctype"] == "slc"
    assert result["controller"]["processor_type"] == PROCESSOR_TYPE.strip()
    assert result["info_error"] == ""


def test_slc_list_tags_returns_the_data_file_directory(slc: TargetConfig) -> None:
    """PCCC has no symbol table, so `eip_list_tags` returns File 0 instead.

    This is the most involved exchange in the connector: a processor-type read to
    choose the File-0 layout, a size probe, then sequential content reads that
    pycomm3 reassembles and parses with byte offsets. A mock returned a dict; only
    a real driver walks that sequence.
    """
    result = ops.eip_list_tags(slc)

    assert result["plctype"] == "slc"
    assert result["file_count"] == len(DATA_FILES), result
    files = {entry["file"]: entry for entry in result["files"]}
    assert files["N7"]["elements"] == 20, files
    assert files["N7"]["length"] == 40, files
    # A 6-byte-per-element file: 10 timers, 60 bytes. Getting the element size
    # wrong would make the counts plausible but wrong.
    assert files["T4"]["elements"] == 10, files
    assert files["T4"]["length"] == 60, files
    assert files["F8"]["length"] == 40, files
    assert result["directory_error"] == ""


def test_slc_reads_each_data_table_shape(slc: TargetConfig) -> None:
    """Integer, negative integer, float, bit and timer accumulator.

    Each is a different decode: N is a signed 16-bit word (65531 would look
    plausible for -5), F is a 32-bit float, a bit read returns one bit out of a
    word, and `T4:0.ACC` is the third word of a six-byte timer element.
    """
    assert ops.eip_read_tag(slc, "N7:0")["value"] == 1750
    assert ops.eip_read_tag(slc, "N7:2")["value"] == -5
    assert ops.eip_read_tag(slc, "F8:0")["value"] == pytest.approx(42.5)
    assert ops.eip_read_tag(slc, "B3:0/3")["value"] is True
    assert ops.eip_read_tag(slc, "B3:0/1")["value"] is False
    assert ops.eip_read_tag(slc, "T4:0.ACC")["value"] == 137

    batch = ops.eip_read_many(slc, ["N7:0", "F8:0", "N7:3"])
    assert [item["value"] for item in batch["items"]] == [1750, pytest.approx(42.5), 32767]
    assert all(item["good"] for item in batch["items"]), batch


def test_slc_bad_address_returns_the_controllers_own_refusal(slc: TargetConfig) -> None:
    """The wire-level error path — which the Logix half of this suite cannot reach.

    pycomm3 validates Logix tag names against the uploaded tag list client-side, so
    a bad Logix tag never leaves the driver. PCCC has no symbol table to validate
    against, so `N7:99` really does go out and the controller really does refuse
    it. This is the only place in the EtherNet/IP connector where a device-side
    rejection is exercised end to end.
    """
    result = ops.eip_read_tag(slc, "N7:99")

    assert result["good"] is False, result
    assert result["value"] is None
    assert "Illegal Command" in result["error"], result


def test_slc_write_captures_before_and_reaches_the_data_table(slc: TargetConfig) -> None:
    """Dry run reads and changes nothing; the real write moves the element."""
    preview = ops.eip_write_tag(slc, "N7:1", 999)
    assert preview["dry_run"] is True
    assert preview["before"] == 4242, preview
    assert ops.eip_read_tag(slc, "N7:1")["value"] == 4242, "the dry run wrote"

    applied = ops.eip_write_tag(slc, "N7:1", 999, dry_run=False)
    assert applied["applied"] is True, applied
    assert applied["before"] == 4242
    assert ops.eip_read_tag(slc, "N7:1")["value"] == 999

    # The captured BEFORE is a usable undo, not a decorative field.
    ops.eip_write_tag(slc, "N7:1", applied["before"], dry_run=False)
    assert ops.eip_read_tag(slc, "N7:1")["value"] == 4242


def test_slc_bit_write_leaves_its_neighbours_alone(slc: TargetConfig) -> None:
    """A PCCC bit write carries a mask — clearing bit 3 must not clear bit 0.

    A device that ignored the mask would pass a test that only re-read the bit it
    wrote. `B3:0` starts as 0b1001, so bit 0 is the witness.
    """
    assert ops.eip_read_tag(slc, "B3:0/0")["value"] is True

    ops.eip_write_tag(slc, "B3:0/3", 0, dry_run=False)

    assert ops.eip_read_tag(slc, "B3:0/3")["value"] is False
    assert ops.eip_read_tag(slc, "B3:0/0")["value"] is True, "the mask was ignored"


# ─── Micro800 ────────────────────────────────────────────────────────────────


def test_micro800_route_reads_tags_and_sends_no_multi_service_packet(
    micro800: TargetConfig, slc: TargetConfig
) -> None:
    """Micro800 controllers cannot batch — pycomm3 must split, and does only if told.

    The switch is not a setting the connector passes: pycomm3 reads the catalog
    number out of ListIdentity and changes behaviour itself. So the assertion has
    to be about what reached the wire. The harness counts Multiple Service Packets;
    a three-tag read against a Micro800 identity must produce **none**, while the
    identical call in `test_eip_live.py`'s Logix fixture produces one.

    `slc` is here only for its port — a second harness process whose identity is
    the plain Logix one, so the comparison is against a live control rather than a
    number remembered from another test file.
    """
    result = ops.eip_read_many(micro800, ["MotorSpeed", "Setpoint", "Temperature"])

    assert [item["value"] for item in result["items"]] == [1750, 4242, pytest.approx(42.5)]
    assert _multiple_service_count(micro800) == 0, (
        "a Multiple Service Packet reached a Micro800 — pycomm3 did not take its "
        "Micro800 path, so the identity the harness answered with was wrong"
    )

    # The control: the same three tags against a controller that identifies as
    # Logix DO get batched, so the assertion above is about the identity and not
    # about the request never being batched at all.
    logix = TargetConfig(
        name="logix-control",
        protocol="ethernetip",
        host=slc.host,
        plctype="logix",
        timeout_s=5,
    )
    ops.eip_read_many(logix, ["MotorSpeed", "Setpoint", "Temperature"])
    assert _multiple_service_count(logix) == 1


def test_micro800_identity_is_what_the_connector_reports(micro800: TargetConfig) -> None:
    """The Micro800 route still reads the CIP identity — it is a Logix driver."""
    result = ops.eip_controller_info(micro800)

    assert result["plctype"] == "micro800"
    assert result["controller"]["product_name"] == MICRO800_PRODUCT_NAME, result


def test_slc_bit_write_on_a_wide_element_is_not_refused(slc: TargetConfig) -> None:
    """A bit write to a 4- or 6-byte file must reach the data table.

    pycomm3 encodes the size byte from the file's ELEMENT width (6 for a timer,
    4 for a float) and only then sets its own `data_size = 2` for the masked
    write — so the request arrives as "size 6, two bytes of data". A device that
    compares the payload length against the declared size refuses it as
    `Illegal Command`, which reads like a bad address for an address that is
    fine. Only `B3` (2 bytes) was covered before, which is exactly the width
    where the mistake is invisible.
    """
    before = ops.eip_read_tag(slc, "T4:0.ACC")["value"]
    assert before == 137

    applied = ops.eip_write_tag(slc, "F8:0", 3.5, dry_run=False)
    assert applied["applied"] is True, applied
    assert ops.eip_read_tag(slc, "F8:0")["value"] == pytest.approx(3.5)

    # A timer's DN flag is a masked write on a 6-byte element (sub-element 13).
    flags = ops.eip_write_tag(slc, "T4:0.DN", 1, dry_run=False)
    assert flags["applied"] is True, flags
    assert "Illegal Command" not in str(flags), flags
    # The accumulator, two words further into the same element, is untouched.
    assert ops.eip_read_tag(slc, "T4:0.ACC")["value"] == 137


def test_slc_string_files_decode_with_their_swapped_words(slc: TargetConfig) -> None:
    """`ST` is a two-letter file type storing byte-swapped words — two traps.

    An SLC string element is a UINT length followed by 82 bytes in which each
    16-bit word holds its two characters BACKWARDS ('AB' is stored 0x4241), and
    `ST` is one of the file types whose name is two letters. Both are invisible
    until a string is actually read: element sizing keyed on the first character
    alone turns `ST` into `S` (2 bytes instead of 84), which returns a string
    from four bytes into the previous element — text that looks almost right.
    """
    assert ops.eip_read_tag(slc, "ST18:0")["value"] == "LINE 1 READY"
    # The second element proves the sizing, not just the swap: with the wrong
    # element width this returns a shifted slice of the first one.
    assert ops.eip_read_tag(slc, "ST18:1")["value"] == "BATCH 42"

    files = {entry["file"]: entry for entry in ops.eip_list_tags(slc)["files"]}
    assert "ST18" in files, files
    assert files["ST18"]["elements"] == 4, files
    # 4 x 84 — a directory that sized ST as 2 bytes would say 336 elements.
    assert files["ST18"]["length"] == 336, files


def test_the_data_file_directory_numbers_files_positionally(slc: TargetConfig) -> None:
    """File numbers come from POSITION in File 0, not from a field.

    `ST18` sits at row 18 with rows 9-17 unused; a File 0 that leaves those rows
    empty makes every later file report under the wrong number (ST18 arrived as
    ST9). Real controllers fill unused slots with a reserved marker, and so does
    the harness now — this asserts the numbering that depends on it.
    """
    files = {entry["file"] for entry in ops.eip_list_tags(slc)["files"]}

    assert {"N7", "F8", "ST18"} <= files, sorted(files)
    assert "ST9" not in files, "the positional numbering slipped — check File 0's gaps"
