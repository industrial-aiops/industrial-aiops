"""HART command codec — build universal command frames + parse device responses.

Wraps the ``hart-protocol`` library (an OPTIONAL extra, ``pip install iaiops[hart]``)
imported LAZILY. This layer is **verified offline**: a crafted HART long-frame ACK
round-trips through the parser (see tests). Only READ/universal commands are built
here — no device-specific or write commands.

A HART device only answers a long frame that carries ITS OWN 5-byte unique
address (manufacturer id + device type + device id). The address is therefore
never defaulted here: callers must supply one — configured, or discovered via
the short-frame command-0 identity poll (:func:`build_identity_poll` →
:func:`unique_address_from_identity`).
"""

from __future__ import annotations

import io
from typing import Any

_LONG_ADDRESS_LEN = 5
_MAX_POLLING_ADDRESS = 63
_PREAMBLE = b"\xFF\xFF\xFF\xFF\xFF"
_SHORT_FRAME_STX = 0x02  # short-frame master→slave start delimiter
_PRIMARY_MASTER_BIT = 0x80


def build_command(name: str, address: bytes) -> bytes:
    """Build a universal HART long-frame command by name (read-only commands only).

    ``address`` is the device's 5-byte unique long address. Raises a ValueError
    for an unknown/unsupported command or a malformed address so a typo fails
    fast rather than silently sending a frame no device will answer.
    """
    from hart_protocol import universal

    builder = _READ_COMMANDS.get(name)
    if builder is None:
        raise ValueError(
            f"Unknown/unsupported HART read command '{name}'. "
            f"Supported: {', '.join(sorted(_READ_COMMANDS))}."
        )
    if len(address) != _LONG_ADDRESS_LEN:
        raise ValueError(
            f"HART long address must be {_LONG_ADDRESS_LEN} bytes "
            f"(manufacturer id + device type + device id), got {len(address)}."
        )
    return getattr(universal, builder)(address=address)


def build_identity_poll(polling_address: int = 0) -> bytes:
    """Build a short-frame command-0 identity poll (the HART discovery read).

    Command 0 addressed by the 1-byte polling address (0 = the point-to-point
    default) is how a master learns a device's unique long address. Pure frame
    construction — preamble + delimiter + address + cmd + byte count + checksum.
    """
    from hart_protocol.tools import calculate_checksum

    if not 0 <= int(polling_address) <= _MAX_POLLING_ADDRESS:
        raise ValueError(
            f"HART polling address must be 0..{_MAX_POLLING_ADDRESS}, "
            f"got {polling_address}."
        )
    core = bytes(
        [_SHORT_FRAME_STX, _PRIMARY_MASTER_BIT | int(polling_address), 0, 0]
    )  # delimiter, address (primary master), command 0, byte count 0
    checksum = calculate_checksum(core)
    checksum = checksum if isinstance(checksum, (bytes, bytearray)) else bytes([checksum])
    return _PREAMBLE + core + checksum


def unique_address_from_identity(message: Any) -> bytes:
    """Derive the 5-byte unique long address from a parsed command-0 response.

    Long address = (manufacturer id & 0x3F) + device type + 3-byte device id.
    Raises a ValueError when the response lacks the identity fields — guessing
    an address would send reads a healthy device silently ignores.
    """
    manufacturer_id = getattr(message, "manufacturer_id", None)
    device_type = getattr(message, "manufacturer_device_type", None)
    device_id = getattr(message, "device_id", None)
    if manufacturer_id is None or device_type is None or device_id is None:
        raise ValueError(
            "HART identity (command 0) response did not carry manufacturer id / "
            "device type / device id — cannot derive the device's unique long "
            "address. Configure 'long_address' explicitly for this endpoint."
        )
    return (
        bytes([int(manufacturer_id) & 0x3F, int(device_type) & 0xFF])
        + int(device_id).to_bytes(3, "big")
    )


def parse_long_address(text: str) -> bytes:
    """Parse a configured 5-byte HART unique address from hex text.

    Accepts ``26:06:12:34:56``, ``26 06 12 34 56`` or ``2606123456``. The top
    two bits of the first byte (master/burst flags on the wire) are masked off.
    Raises a ValueError for malformed input.
    """
    cleaned = "".join(ch for ch in str(text) if ch not in " :-_")
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"HART long_address '{text}' is not valid hex. Expected 5 bytes, "
            f"e.g. '26:06:12:34:56'."
        ) from exc
    if len(raw) != _LONG_ADDRESS_LEN:
        raise ValueError(
            f"HART long_address '{text}' must be {_LONG_ADDRESS_LEN} bytes "
            f"(manufacturer id + device type + device id), got {len(raw)}."
        )
    return bytes([raw[0] & 0x3F]) + raw[1:]


# name → hart_protocol.universal builder (read/universal only; no writes).
_READ_COMMANDS = {
    "unique_identifier": "read_unique_identifier",
    "primary_variable": "read_primary_variable",
    "loop_current_and_percent": "read_loop_current_and_percent",
    "dynamic_variables": "read_dynamic_variables_and_loop_current",
    "primary_variable_information": "read_primary_variable_information",
}


class _ByteShim:
    """A minimal pyserial-like file object over a bytes buffer for ``Unpacker``.

    ``hart_protocol.Unpacker`` reads from a stream exposing ``in_waiting`` + a
    ``read(n)``; HART-IP hands us a complete datagram, so we wrap those bytes.
    """

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    @property
    def in_waiting(self) -> int:
        pos = self._buf.tell()
        self._buf.seek(0, io.SEEK_END)
        end = self._buf.tell()
        self._buf.seek(pos)
        return end - pos

    def read(self, size: int = 1) -> bytes:
        return self._buf.read(size)


def parse_responses(data: bytes) -> list[Any]:
    """Parse raw HART response bytes into hart-protocol message objects.

    Returns the list of parsed messages (each exposes ``command``,
    ``primary_variable``, etc.). Invalid trailing bytes are discarded by the
    library's ``on_error='continue'`` policy rather than raising.
    """
    from hart_protocol import Unpacker

    return list(Unpacker(_ByteShim(data), on_error="continue"))


__all__ = [
    "build_command",
    "build_identity_poll",
    "parse_long_address",
    "parse_responses",
    "unique_address_from_identity",
]
