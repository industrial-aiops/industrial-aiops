"""HART command codec — build universal command frames + parse device responses.

Wraps the ``hart-protocol`` library (an OPTIONAL extra, ``pip install iaiops[hart]``)
imported LAZILY. This layer is **verified offline**: a crafted HART long-frame ACK
round-trips through the parser (see tests). Only READ/universal commands are built
here — no device-specific or write commands.

Addressing: a HART device only answers a long frame that carries its OWN 5-byte
unique address (expanded device type + device id), so there is no usable default
address. The address is either configured (``long_address`` on the endpoint) and
parsed by :func:`parse_long_address`, or discovered with a short-frame Command 0
identity poll (:func:`build_poll_command`) whose answer feeds
:func:`unique_address_from_identity`.
"""

from __future__ import annotations

import io
import re
from typing import Any

# A HART unique long address is 5 bytes: expanded device type (2) + device id (3).
LONG_ADDRESS_BYTES = 5
# Valid polling addresses for short-frame (Command 0) discovery: 0-63 (HART 6/7;
# HART 5 used 0-15). Point-to-point devices always sit at polling address 0.
MAX_POLL_ADDRESS = 63
_SHORT_FRAME_DELIMITER = 0x02  # STX, master → device, short (1-byte-address) frame
_PRIMARY_MASTER_BIT = 0x80
_PREAMBLE = b"\xFF" * 5


def parse_long_address(text: str) -> bytes:
    """Parse a configured HART ``long_address`` into its 5 raw bytes.

    Accepts exactly 10 hex digits, with optional spaces/colons/dashes between
    bytes: ``"26 06 12 34 56"``, ``"2606123456"``, or ``"26:06:12:34:56"``.
    """
    cleaned = re.sub(r"[\s:\-]", "", str(text))
    if not re.fullmatch(r"[0-9a-fA-F]{10}", cleaned):
        raise ValueError(
            f"Invalid HART long_address {text!r}: expected 10 hex digits "
            f"(5 bytes = expanded device type + device id), e.g. '26 06 12 34 56'. "
            f"Read it from the device label or leave it unset to auto-discover "
            f"via Command 0."
        )
    return bytes.fromhex(cleaned)


def build_poll_command(poll_address: int = 0) -> bytes:
    """Build a SHORT-frame Command 0 (read unique identifier) for discovery.

    The ``hart-protocol`` library only packs long frames (``pack_command`` always
    emits delimiter 0x82 + a 5-byte address), so the short frame a device answers
    BEFORE its unique address is known is packed here: preamble + STX 0x02 +
    (primary-master bit | polling address) + command 0 + byte count 0 + the same
    XOR checksum the library computes over everything after the preamble.
    """
    from hart_protocol.tools import calculate_checksum

    address = int(poll_address)
    if not 0 <= address <= MAX_POLL_ADDRESS:
        raise ValueError(
            f"Invalid HART polling address {poll_address!r}: must be "
            f"0-{MAX_POLL_ADDRESS} (0 = the point-to-point default)."
        )
    core = bytes([_SHORT_FRAME_DELIMITER, _PRIMARY_MASTER_BIT | address, 0x00, 0x00])
    return _PREAMBLE + core + calculate_checksum(core)


def unique_address_from_identity(msg: Any) -> bytes:
    """Derive the 5-byte unique address from a parsed Command 0 identity message.

    Per the HART spec the unique address is the expanded device type (the
    manufacturer-id byte masked to its low 6 bits + the device-type byte)
    followed by the 3-byte device id.
    """
    manufacturer_id = getattr(msg, "manufacturer_id", None)
    device_type = getattr(msg, "manufacturer_device_type", None)
    device_id = getattr(msg, "device_id", None)
    if manufacturer_id is None or device_type is None or device_id is None:
        raise ValueError(
            "HART Command 0 answer is missing identity fields (manufacturer id / "
            "device type / device id), so the device's unique address cannot be "
            "derived. Set 'long_address' on the endpoint to address it explicitly."
        )
    from hart_protocol import tools

    return tools.calculate_long_address(
        int(manufacturer_id) & 0x3F,
        int(device_type) & 0xFF,
        (int(device_id) & 0xFFFFFF).to_bytes(3, "big"),
    )


def build_command(name: str, address: bytes) -> bytes:
    """Build a universal HART long-frame command by name (read-only commands only).

    ``address`` is the device's REAL 5-byte unique address (configured or
    discovered via Command 0) — a device ignores long frames carrying any other
    address, so a fabricated default would only ever time out. Raises a
    ValueError for an unknown/unsupported command so a typo fails fast.
    """
    from hart_protocol import universal

    if len(address) != LONG_ADDRESS_BYTES:
        raise ValueError(
            f"HART long address must be {LONG_ADDRESS_BYTES} bytes, got "
            f"{len(address)} ({address!r})."
        )
    builder = _READ_COMMANDS.get(name)
    if builder is None:
        raise ValueError(
            f"Unknown/unsupported HART read command '{name}'. "
            f"Supported: {', '.join(sorted(_READ_COMMANDS))}."
        )
    return getattr(universal, builder)(address=address)


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
    "LONG_ADDRESS_BYTES",
    "MAX_POLL_ADDRESS",
    "build_command",
    "build_poll_command",
    "parse_long_address",
    "parse_responses",
    "unique_address_from_identity",
]
