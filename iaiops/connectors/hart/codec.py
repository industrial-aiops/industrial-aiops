"""HART command codec — build universal command frames + parse device responses.

Wraps the ``hart-protocol`` library (an OPTIONAL extra, ``pip install iaiops[hart]``)
imported LAZILY. This layer is **verified offline**: a crafted HART long-frame ACK
round-trips through the parser (see tests). Only READ/universal commands are built
here — no device-specific or write commands.
"""

from __future__ import annotations

import io
from typing import Any

# HART polling/long-address default for a point-to-point read (master, primary).
DEFAULT_LONG_ADDRESS = b"\x80\x00"


def build_command(name: str, address: bytes = DEFAULT_LONG_ADDRESS) -> bytes:
    """Build a universal HART command frame by name (read-only commands only).

    Raises a ValueError for an unknown/unsupported command so a typo fails fast
    rather than silently sending nothing.
    """
    from hart_protocol import universal

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


__all__ = ["build_command", "parse_responses", "DEFAULT_LONG_ADDRESS"]
