"""Modbus transport: TCP/RTU client build + error translation (from connection.py).

The assembled ``modbus_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_modbus_client``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _is_modbus_rtu(target: TargetConfig) -> bool:
    """True when a Modbus endpoint uses the serial (RTU) transport."""
    return target.transport == "rtu" or bool(target.serial_port)


def _modbus_endpoint_str(target: TargetConfig) -> str:
    """Human-readable endpoint locator for a Modbus target (serial or TCP)."""
    if _is_modbus_rtu(target):
        return f"{target.serial_port or '?'}@{target.baudrate}"
    return f"{target.host}:{target.port or 502}"


def _build_modbus_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pymodbus client for ``target``.

    Builds a ``ModbusSerialClient`` when the endpoint uses the RTU (serial)
    transport, otherwise a ``ModbusTcpClient``. The same read ops (holding /
    input / coils / discrete) work over either. Separated out so tests can
    monkeypatch this with a mock client — and so the serial client construction
    can be verified without live hardware.
    """
    if _is_modbus_rtu(target):
        return _build_modbus_serial_client(target)

    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError as exc:  # pragma: no cover — exercised only without pymodbus
        raise OTConnectionError(
            "The 'pymodbus' package is not installed. Install the Modbus "
            "connector: 'pip install iaiops[modbus]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"Modbus endpoint '{target.name}' has no host. Add 'host: <ip>' to its "
            f"config entry (or set 'transport: rtu' + 'serial_port:' for serial).",
            endpoint=target.name,
            protocol="modbus",
        )
    return ModbusTcpClient(target.host, port=target.port or 502, timeout=target.timeout_s)


def _build_modbus_serial_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pymodbus ModbusSerialClient (Modbus-RTU).

    ``ModbusSerialClient`` defaults to the RTU framer; we pass the serial line
    params (baudrate / parity / stopbits / bytesize) from the endpoint config.
    The live serial round-trip needs real hardware (待核实 — not CI-verifiable);
    this construction is unit-tested by monkeypatching the pymodbus client.
    """
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError as exc:  # pragma: no cover — exercised only without pymodbus
        raise OTConnectionError(
            "The 'pymodbus' package is not installed. Install the Modbus "
            "connector: 'pip install iaiops[modbus]' (serial needs pyserial too).",
            endpoint=target.name,
            protocol="modbus",
        ) from exc

    if not target.serial_port:
        raise OTConnectionError(
            f"Modbus-RTU endpoint '{target.name}' has no serial_port. Add "
            f"'serial_port: /dev/ttyUSB0' (or a COM port) to its config entry.",
            endpoint=target.name,
            protocol="modbus",
        )
    return ModbusSerialClient(
        target.serial_port,
        baudrate=target.baudrate or 19200,
        parity=(target.parity or "N")[:1],
        stopbits=target.stopbits or 1,
        bytesize=target.bytesize or 8,
        timeout=target.timeout_s,
    )


def _connect_modbus(client: Any, target: TargetConfig) -> None:
    """Connect a pymodbus client; ``connect() is False`` becomes a teaching error."""
    connected = client.connect()
    if connected is False:
        where = _modbus_endpoint_str(target)
        if _is_modbus_rtu(target):
            detail = (
                f"Could not open Modbus-RTU serial line '{target.name}' ({where}). "
                f"Check the serial_port, baudrate/parity/stopbits, cabling and that no "
                f"other process holds the port. Live serial needs real hardware."
            )
        else:
            detail = (
                f"Could not connect to Modbus endpoint '{target.name}' ({where}). Check "
                f"the host/port and that the PLC's Modbus-TCP server is enabled. Point "
                f"at a local simulator to test."
            )
        raise OTConnectionError(detail, endpoint=where, protocol="modbus")


def _translate_modbus(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pymodbus exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = _modbus_endpoint_str(target)
    return OTConnectionError(
        f"Modbus operation on '{target.name}' ({endpoint}) failed: {detail}",
        endpoint=endpoint,
        protocol="modbus",
    )


__all__ = [
    "_build_modbus_client",
    "_build_modbus_serial_client",
    "_connect_modbus",
    "_is_modbus_rtu",
    "_modbus_endpoint_str",
    "_translate_modbus",
]
