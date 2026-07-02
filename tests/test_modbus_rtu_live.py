"""Live Modbus-RTU (serial) round-trip test — no physical hardware.

This is the ONLY test that exercises the connector's real serial framing path.
Every other Modbus test monkeypatches the pymodbus client; here we stand up a
REAL serial link and prove ``modbus_read_holding`` / ``modbus_read_input`` /
``modbus_read_coils`` / ``modbus_read_discrete`` decode seeded registers that
travelled over an actual RTU wire.

How the fake wire is built (no hardware, no root):

  * ``socat -d -d pty,raw,echo=0 pty,raw,echo=0`` creates a pair of connected
    pseudo-terminals (PTYs). Bytes written to one appear on the other — a
    software stand-in for a null-modem serial cable.
  * A pymodbus ``ModbusSerialServer`` (RTU framer) is bound to one PTY, seeded
    with known holding/input registers, coils and discrete inputs, and served on
    a background asyncio loop.
  * The connector connects a real ``ModbusSerialClient`` to the OTHER PTY via
    ``TargetConfig(transport="rtu", serial_port=...)`` and runs the read ops.

It is ``integration``-marked and SKIPS cleanly when ``socat`` or ``pyserial`` is
unavailable (e.g. the macOS host), so the default quality gate is unaffected.
Run it where socat exists (Linux / Docker)::

    pytest -m integration tests/test_modbus_rtu_live.py

待核实 → verified: exercised locally in a python:3.12-slim container (socat PTY
pair + pymodbus RTU server); not run in CI (no socat) and not validated against a
specific physical RTU device / RS-485 bus.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import struct
import subprocess  # nosec B404 — spawns the local `socat` helper only, no shell
import threading
from collections.abc import Iterator
from typing import Any

import pytest

# Skip cleanly when the serial stack or the socat helper is absent (host default).
pytest.importorskip("serial", reason="pyserial not installed — Modbus-RTU serial needs it")
pytest.importorskip("pymodbus", reason="pymodbus not installed — install iaiops[modbus]")

from iaiops.connectors.modbus import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

_SOCAT = shutil.which("socat")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _SOCAT is None,
        reason="socat not found — run on Linux/Docker to exercise Modbus-RTU live serial",
    ),
]

_BAUD = 19200

# ─── seeded register maps (by protocol meaning, address-aligned) ──────────────

# Holding registers (served on FC03) 0..19: a distinctive ramp so an off-by-one
# would be obvious. Encode a float32 (42.5, big-endian word order) into the pair
# at addresses 10/11 to prove the connector's float32 decode over real framing.
_HOLDING_VALUES: list[int] = [1000 + i for i in range(20)]
_F_HI, _F_LO = struct.unpack(">HH", struct.pack(">f", 42.5))
_HOLDING_VALUES[10] = _F_HI
_HOLDING_VALUES[11] = _F_LO

# Input registers (served on FC04) 0..19: a separate ramp so a holding/input
# mix-up would be obvious.
_INPUT_VALUES: list[int] = [2000 + i for i in range(20)]
_CO_VALUES: list[bool] = [True, False, True, True, False, False, True, False]
_DI_VALUES: list[bool] = [False, True, True, False, True, False, False, True]


# ─── socat PTY pair ───────────────────────────────────────────────────────────


def _socat_pty_pair() -> tuple[subprocess.Popen[str], str, str]:
    """Spawn socat, return (process, pty_a, pty_b) once both PTYs are announced."""
    proc = subprocess.Popen(  # nosec B603 — fixed argv, resolved socat path, no shell
        [_SOCAT, "-d", "-d", "pty,raw,echo=0", "pty,raw,echo=0"],
        stderr=subprocess.PIPE,
        text=True,
    )
    ptys: list[str] = []
    assert proc.stderr is not None
    for _ in range(20):  # bounded: socat prints the two PTY lines up front
        line = proc.stderr.readline()
        if not line:
            break
        match = re.search(r"PTY is (\S+)", line)
        if match:
            ptys.append(match.group(1))
        if len(ptys) == 2:
            break
    if len(ptys) < 2:
        proc.terminate()
        pytest.skip("socat did not report two PTYs")
    return proc, ptys[0], ptys[1]


# ─── pymodbus RTU server on a background asyncio loop ─────────────────────────


def _build_context() -> Any:
    from pymodbus.datastore import (
        ModbusDeviceContext,
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )

    # pymodbus 3.13 ``ModbusSequentialDataBlock`` is 1-based: it stores at
    # ``address - 1`` internally, so base ``1`` seeds protocol register address 0.
    base = 1
    # NOTE: pymodbus 3.13's DEPRECATED ``ModbusDeviceContext`` wires the register
    # blocks to function codes SWAPPED — FC03 (read_holding) is served by the
    # ``ir=`` block and FC04 (read_input) by the ``hr=`` block (coils/discrete map
    # normally). This is a scaffolding-only quirk of the compat shim; the connector
    # under test issues the correct function codes. We seed by protocol meaning and
    # pass each block to the kwarg that actually serves it, so ``modbus_read_holding``
    # returns the holding values and ``modbus_read_input`` the input values — exactly
    # what a real RTU device would return.
    device = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(base, _INPUT_VALUES),  # served on FC04 (input)
        ir=ModbusSequentialDataBlock(base, _HOLDING_VALUES),  # served on FC03 (holding)
        co=ModbusSequentialDataBlock(base, [int(b) for b in _CO_VALUES]),
        di=ModbusSequentialDataBlock(base, [int(b) for b in _DI_VALUES]),
    )
    return ModbusServerContext(devices=device, single=True)


class _RtuServer:
    """Runs a pymodbus RTU serial server on a private background event loop."""

    def __init__(self, serial_port: str) -> None:
        self._serial_port = serial_port
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._server: Any = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _start(self) -> Any:
        from pymodbus.framer import FramerType
        from pymodbus.server import ModbusSerialServer

        server = ModbusSerialServer(
            _build_context(),
            framer=FramerType.RTU,
            port=self._serial_port,
            baudrate=_BAUD,
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=1,
        )
        await server.serve_forever(background=True)
        return server

    def start(self) -> None:
        self._thread.start()
        self._server = asyncio.run_coroutine_threadsafe(
            self._start(), self._loop
        ).result(timeout=10)

    def stop(self) -> None:
        if self._server is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._server.shutdown(), self._loop
                ).result(timeout=10)
            except Exception:  # noqa: BLE001 — teardown must not mask a test failure
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@pytest.fixture()
def rtu_target() -> Iterator[TargetConfig]:
    """Stand up socat + an RTU server; yield a client-side TargetConfig."""
    proc, server_pty, client_pty = _socat_pty_pair()
    server = _RtuServer(server_pty)
    try:
        server.start()
        yield TargetConfig(
            name="modbus-rtu-live",
            protocol="modbus",
            transport="rtu",
            serial_port=client_pty,
            baudrate=_BAUD,
            parity="N",
            stopbits=1,
            bytesize=8,
            unit_id=1,
        )
    finally:
        server.stop()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover — best-effort cleanup
            proc.kill()


# ─── the real round-trip assertions ───────────────────────────────────────────


def test_rtu_read_holding_registers(rtu_target: TargetConfig) -> None:
    out = ops.modbus_read_holding(rtu_target, address=0, count=6, decode="uint16")
    assert out["raw_registers"] == _HOLDING_VALUES[0:6]
    assert out["unit_id"] == 1
    assert out["decode"] == "uint16"


def test_rtu_read_holding_float32_decode(rtu_target: TargetConfig) -> None:
    out = ops.modbus_read_holding(rtu_target, address=10, count=2, decode="float32")
    assert out["raw_registers"] == [_F_HI, _F_LO]
    assert out["decoded"] == [42.5]


def test_rtu_read_input_registers(rtu_target: TargetConfig) -> None:
    out = ops.modbus_read_input(rtu_target, address=0, count=5, decode="uint16")
    assert out["raw_registers"] == _INPUT_VALUES[0:5]


def test_rtu_read_coils(rtu_target: TargetConfig) -> None:
    out = ops.modbus_read_coils(rtu_target, address=0, count=len(_CO_VALUES))
    assert out["bits"] == _CO_VALUES


def test_rtu_read_discrete_inputs(rtu_target: TargetConfig) -> None:
    out = ops.modbus_read_discrete(rtu_target, address=0, count=len(_DI_VALUES))
    assert out["bits"] == _DI_VALUES
