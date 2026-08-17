"""Live Modbus-TCP round-trip test — real MBAP framing, no hardware.

Modbus **RTU** has had a real wire since ``test_modbus_rtu_live.py``; Modbus
**TCP** — by far the more common transport in the field — had none. Every other
TCP test monkeypatches ``_build_modbus_client``, so the code that assembles and
parses the **MBAP header** (transaction id / protocol id / length / unit id) had
never moved a byte. That framing layer is entirely different from RTU's CRC
framing: sharing the read ops does not mean sharing the transport path.

The server is a real ``pymodbus`` ``ModbusTcpServer`` on a loopback port, seeded
with known banks; the connector connects a real ``ModbusTcpClient`` through the
ordinary ``TargetConfig`` path. Nothing is patched.

Beyond the four read ops this also covers two paths that only exist against a
device and that a mock cannot falsify:

* ``modbus_apply_template`` — a template declares whether its registers live in
  the **holding** or **input** file, and picks the function code accordingly. Get
  that wrong and a mock still returns "the registers", because the mock has only
  one bank. Here the two banks hold deliberately different values, so reading the
  wrong file produces visibly wrong engineering units.
* an out-of-range read must surface a **teaching error**, not a fabricated value.
  That is the OT-honesty invariant, and it had never been checked against a real
  server's exception response for TCP.

Runs wherever pymodbus is installed — no socat, no root, no container — so unlike
the RTU test it is not platform-gated.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("pymodbus", reason="pymodbus not installed — install iaiops[modbus]")

from iaiops.connectors.modbus import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]

# ─── seeded register maps (by protocol meaning, address-aligned) ──────────────

# Distinct ramps per bank so a holding/input mix-up is visible rather than
# plausible. float32 42.5 lands in the holding pair at 10/11 (big-endian words).
#
# 80 registers, not 20: the built-in templates that declare the INPUT file are the
# wide ones (eastron_sdm630 spans 72), and a template test that only ever exercises
# the holding file cannot catch a wrong function code. The window is sized by what
# it takes to cover both banks, not by what is convenient.
_BANK_SIZE = 80
_HOLDING_VALUES: list[int] = [1000 + i for i in range(_BANK_SIZE)]
_F_HI, _F_LO = struct.unpack(">HH", struct.pack(">f", 42.5))
_HOLDING_VALUES[10] = _F_HI
_HOLDING_VALUES[11] = _F_LO

_INPUT_VALUES: list[int] = [2000 + i for i in range(_BANK_SIZE)]
_CO_VALUES: list[bool] = [True, False, True, True, False, False, True, False]
_DI_VALUES: list[bool] = [False, True, True, False, True, False, False, True]

_UNIT_ID = 1


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_context() -> Any:
    from pymodbus.datastore import (
        ModbusDeviceContext,
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )

    # ``ModbusSequentialDataBlock`` is 1-based (stores at ``address - 1``), so
    # base 1 seeds protocol register address 0.
    #
    # Seeded by PROTOCOL MEANING — ``hr=`` is FC03, ``ir=`` is FC04. Deliberately
    # NOT compensating for any library quirk: the RTU sibling of this file once
    # swapped these to cancel out a pymodbus 3.13 defect, and when 3.14 fixed the
    # defect upstream the compensation silently became the bug. ``_assert_wiring``
    # re-checks the premise at runtime instead of trusting it.
    device = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(1, _HOLDING_VALUES),
        ir=ModbusSequentialDataBlock(1, _INPUT_VALUES),
        co=ModbusSequentialDataBlock(1, [int(b) for b in _CO_VALUES]),
        di=ModbusSequentialDataBlock(1, [int(b) for b in _DI_VALUES]),
    )
    return ModbusServerContext(devices=device, single=True)


#: FC43 / MEI-14 identity the server answers with. Deliberately distinctive so a
#: decoded field cannot accidentally match a library default.
_IDENT_VENDOR = "Acme Industrial 工业"
_IDENT_PRODUCT = "PLC-9000"
_IDENT_REVISION = "V3.14"


def _build_identity() -> Any:
    """Seed FC43 device identification on the server.

    Note a real pymodbus quirk found while checking this: identity state is shared
    process-wide, so a server started with ``identity=None`` still answers with
    whatever a previously-constructed identity held. Verified in a clean process,
    ``identity=None`` returns ``information={}`` — an empty answer, NOT an
    exception. That is why ``modbus_read_device_identification`` treats an empty
    object set as "identified as Modbus-speaking and nothing more" rather than an
    error, and why it never fills in a placeholder vendor.
    """
    from pymodbus.pdu.device import ModbusDeviceIdentification

    identity = ModbusDeviceIdentification()
    identity.VendorName = _IDENT_VENDOR
    identity.ProductCode = _IDENT_PRODUCT
    identity.MajorMinorRevision = _IDENT_REVISION
    return identity


class _TcpServer:
    """A real pymodbus TCP server on a private background event loop."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._server: Any = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _start(self) -> Any:
        from pymodbus.server import ModbusTcpServer

        server = ModbusTcpServer(
            _build_context(),
            identity=_build_identity(),
            address=("127.0.0.1", self._port),
        )
        await server.serve_forever(background=True)
        return server

    def start(self) -> None:
        self._thread.start()
        self._server = asyncio.run_coroutine_threadsafe(self._start(), self._loop).result(
            timeout=10
        )

    def stop(self) -> None:
        if self._server is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._server.shutdown(), self._loop).result(
                    timeout=10
                )
            except Exception:  # noqa: BLE001 — teardown must not mask a test failure
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@pytest.fixture(scope="module")
def tcp_target() -> Iterator[TargetConfig]:
    port = _free_port()
    server = _TcpServer(port)
    try:
        # start() inside the try: it spawns the background loop thread before it can
        # fail, so a failure outside would leak that thread for the whole session.
        server.start()
        yield TargetConfig(
            name="modbus-tcp-live",
            protocol="modbus",
            host="127.0.0.1",
            port=port,
            unit_id=_UNIT_ID,
        )
    finally:
        server.stop()


def _assert_wiring(target: TargetConfig) -> None:
    """Fail fast if the scaffolding does not wire FC03/FC04 per spec.

    Checks the premise rather than assuming it — see the note in ``_build_context``.
    A swapped result is announced with the pymodbus version and skipped; the
    expectations are never re-oriented to match whatever came out.
    """
    hold = ops.modbus_read_holding(target, address=0, count=1, decode="uint16")
    inp = ops.modbus_read_input(target, address=0, count=1, decode="uint16")
    got = (hold.get("raw_registers"), inp.get("raw_registers"))
    want = ([_HOLDING_VALUES[0]], [_INPUT_VALUES[0]])
    if got == (want[1], want[0]):
        import pymodbus

        pytest.skip(
            f"pymodbus {pymodbus.__version__} serves FC03 from the ir= block and FC04 "
            "from hr= (fixed in 3.14) — the scaffolding cannot present a spec-correct "
            "device, so function-code selection cannot be verified here."
        )
    assert got == want, (
        f"TCP scaffolding did not return the seeded banks: FC03 -> {got[0]} "
        f"(seeded {want[0]}), FC04 -> {got[1]} (seeded {want[1]})"
    )


@pytest.fixture()
def tcp_registers(tcp_target: TargetConfig) -> TargetConfig:
    """``tcp_target`` plus the FC03/FC04 premise check.

    Scoped to the register tests: the coil and discrete paths do not depend on the
    hr/ir wiring, so they keep running even where it is wrong. A premise check
    should cost only the coverage that genuinely depends on it.
    """
    _assert_wiring(tcp_target)
    return tcp_target


# ─── the four read paths, over real MBAP framing ─────────────────────────────


def test_tcp_read_holding_registers(tcp_registers: TargetConfig) -> None:
    out = ops.modbus_read_holding(tcp_registers, address=0, count=6, decode="uint16")
    assert out["raw_registers"] == _HOLDING_VALUES[0:6]
    assert out["unit_id"] == _UNIT_ID
    assert out["decode"] == "uint16"


def test_tcp_read_holding_float32_decode(tcp_registers: TargetConfig) -> None:
    out = ops.modbus_read_holding(tcp_registers, address=10, count=2, decode="float32")
    assert out["raw_registers"] == [_F_HI, _F_LO]
    assert out["decoded"] == [42.5]


def test_tcp_read_input_registers(tcp_registers: TargetConfig) -> None:
    out = ops.modbus_read_input(tcp_registers, address=0, count=5, decode="uint16")
    assert out["raw_registers"] == _INPUT_VALUES[0:5]


def test_tcp_read_coils(tcp_target: TargetConfig) -> None:
    out = ops.modbus_read_coils(tcp_target, address=0, count=len(_CO_VALUES))
    assert out["bits"] == _CO_VALUES


def test_tcp_read_discrete_inputs(tcp_target: TargetConfig) -> None:
    out = ops.modbus_read_discrete(tcp_target, address=0, count=len(_DI_VALUES))
    assert out["bits"] == _DI_VALUES


def test_tcp_offset_read_lands_on_the_right_registers(tcp_registers: TargetConfig) -> None:
    """A non-zero start address must not be off by one — the classic Modbus bug,
    invisible against a mock that ignores the address it was handed."""
    out = ops.modbus_read_holding(tcp_registers, address=5, count=3, decode="uint16")
    assert out["raw_registers"] == _HOLDING_VALUES[5:8]


# ─── paths that only exist against a device ──────────────────────────────────


def test_tcp_template_reads_the_register_file_it_declares(tcp_registers: TargetConfig) -> None:
    """``modbus_apply_template`` picks FC03 or FC04 from the template's declared
    register file. A mock has one bank, so a wrong choice still "works" there;
    here the two banks differ, so reading the wrong one is visible in the values.
    """
    from iaiops.connectors.modbus import templates

    names = [t["name"] for t in templates.list_templates()]
    assert names, "no built-in templates to exercise"

    checked_holding = checked_input = 0
    for name in names:
        tmpl = templates.get_template(name)
        if tmpl.base_offset + tmpl.span > len(_HOLDING_VALUES):
            continue  # outside the seeded window — not this test's subject

        live = ops.modbus_apply_template(tcp_registers, name)

        # Oracle: the SAME pure decoder, fed the bank the template declares. Any
        # difference is therefore the transport picking the wrong function code,
        # not a disagreement about how to decode.
        bank = _INPUT_VALUES if tmpl.register_type == "input" else _HOLDING_VALUES
        window = bank[tmpl.base_offset : tmpl.base_offset + tmpl.span]
        expected = templates.apply_template(name, window, start_address=tmpl.base_offset)

        assert live["tags"] == expected["tags"], (
            f"template {name!r} declares register_type={tmpl.register_type!r}; the values "
            "that came off the wire are not what that bank holds"
        )
        if tmpl.register_type == "input":
            checked_input += 1
        else:
            checked_holding += 1

    assert checked_holding and checked_input, (
        "this test only means something when BOTH register files are exercised — "
        f"holding={checked_holding}, input={checked_input}. With one file only, a "
        "wrong function code would still pass."
    )


def test_tcp_template_on_the_wrong_bank_would_be_caught(tcp_registers: TargetConfig) -> None:
    """Guards the test above from passing vacuously.

    The banks must actually differ where the templates read, otherwise "read the
    wrong file" and "read the right file" produce the same answer and the previous
    assertion proves nothing.
    """
    from iaiops.connectors.modbus import templates

    tmpl = templates.get_template("generic_float32_be")
    span = slice(tmpl.base_offset, tmpl.base_offset + tmpl.span)
    right = templates.apply_template(
        "generic_float32_be", _HOLDING_VALUES[span], start_address=tmpl.base_offset
    )
    wrong = templates.apply_template(
        "generic_float32_be", _INPUT_VALUES[span], start_address=tmpl.base_offset
    )
    assert right["tags"] != wrong["tags"], "the two seeded banks decode identically"


def test_tcp_health_summary_reads_real_registers(tcp_registers: TargetConfig) -> None:
    """The health path opens its own session and reads address by address — a
    different call shape from the block reads above, and equally unexercised over
    a wire until now."""
    out = ops.modbus_health_summary(tcp_registers, addresses=[0, 1, 2])
    assert out["evaluated"] == 3
    assert out["overall"] in ("ok", "warn", "alarm", "unknown")
    assert sum(out["counts"].values()) == 3


# ─── the honesty invariant, against a real exception response ────────────────


def test_tcp_out_of_range_read_teaches_rather_than_fabricates(
    tcp_registers: TargetConfig,
) -> None:
    """A device that answers "illegal data address" must surface as an error the
    operator can act on — never as a value. Fabricating here would put an invented
    number in front of someone deciding whether to touch a live process.

    The seeded block is _BANK_SIZE registers; 5000 is far past the end, so a
    spec-conformant server replies with a Modbus exception rather than data.
    """
    from iaiops.core.runtime.connection import OTConnectionError

    with pytest.raises((OTConnectionError, ValueError, RuntimeError)) as excinfo:
        ops.modbus_read_holding(tcp_registers, address=5000, count=2, decode="uint16")

    message = str(excinfo.value)
    assert message.strip(), "the error carried no message for the operator to act on"
    assert "5000" in message or "address" in message.lower(), (
        f"the error does not name what went wrong: {message!r}"
    )


# ─── FC43 identification, against a real MEI-14 exchange ─────────────────────


def test_tcp_device_identification_round_trip(tcp_target: TargetConfig) -> None:
    """FC43 over real MBAP framing, decoded from real bytes.

    A fake can agree with the decoder it was written against; this cannot. The
    vendor string carries non-ASCII on purpose — a device that answers with
    latin-1 or UTF-8 product names is common, and silently mangling one would put
    a wrong vendor into an asset register.
    """
    out = ops.modbus_read_device_identification(tcp_target)

    assert out["vendor"] == _IDENT_VENDOR
    assert out["product_code"] == _IDENT_PRODUCT
    assert out["revision"] == _IDENT_REVISION
    assert out["unit_id"] == _UNIT_ID
    assert out["object_count"] == 3
    assert out["objects"]["vendor_name"] == _IDENT_VENDOR
    assert out["more_follows"] is False


def test_tcp_identification_touches_no_registers(tcp_target: TargetConfig) -> None:
    """The whole point of using FC43 to identify a device is that it asks the
    protocol layer, not the process image. Reading holding register 0 instead —
    the obvious alternative — is a data-plane request against an address the
    device may not map, and legacy slaves answer an unmapped address by raising,
    dropping the session, or faulting.

    Proven by making every register read on this connector explode for the
    duration: identification must still succeed.
    """
    import pytest as _pytest

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("identification reached for a register read")

    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(ops, "_read_registers", forbidden)
        monkeypatch.setattr(ops, "_read_bits", forbidden)
        out = ops.modbus_read_device_identification(tcp_target)
    finally:
        monkeypatch.undo()

    assert out["vendor"] == _IDENT_VENDOR
