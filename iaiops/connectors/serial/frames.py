"""Bytes → lines → readings for serial ASCII instruments (pure; HLD §17.4).

``LineFramer`` cuts a byte stream into lines at the profile's terminator. A line
longer than ``max_line`` or not decodable in the profile's encoding is not
truncated or "repaired": it comes out as ``(None, reason)`` so the caller records
a gap with the reason.

``decode_line`` applies a channel's ascii layout. The pattern must match the
WHOLE line (rule 5: no "parse as best we can"); a status code that is not ``ok``
— unstable, overload, or simply unknown — is not a reading; a unit taken from the
line must agree with a fixed unit when both are declared.
"""

from __future__ import annotations

import functools
import math
import re

from iaiops.core.runtime.sensor import Channel, InvalidReadingError, Reading
from iaiops.core.runtime.sensor.decode import _finish

#: Characters of a refused line quoted back in the reason.
SNIPPET = 48
#: A number as an instrument writes it — no `1_000` (float() accepts that),
#: no `nan` / `inf`, no surrounding spaces.
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


@functools.lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _snippet(line: str) -> str:
    return repr(line if len(line) <= SNIPPET else line[:SNIPPET] + "…")


class LineFramer:
    """Accumulates bytes; ``feed`` returns completed ``(line | None, reason)`` pairs."""

    def __init__(self, terminator: str, encoding: str, max_line: int, synced: bool = True) -> None:
        self._terminator = terminator.encode("ascii")
        self._encoding = encoding
        self._max = max_line
        self._buffer = b""
        self._overlong = False
        #: False right after a link opens mid-stream: everything before the first
        #: terminator is the TAIL of a line ("2.50 kg" of "12.50 kg") and is dropped.
        self._synced = synced

    def reset(self, synced: bool = True) -> None:
        """Forget buffered bytes (after flushing the input)."""
        self._buffer, self._overlong, self._synced = b"", False, synced

    def feed(self, data: bytes) -> list[tuple[str | None, str]]:
        self._buffer += data
        out: list[tuple[str | None, str]] = []
        if not self._synced:
            index = self._buffer.find(self._terminator)
            if index < 0:
                self._buffer = self._buffer[-len(self._terminator) :]
                return out
            self._buffer = self._buffer[index + len(self._terminator) :]
            self._synced = True
        while True:
            index = self._buffer.find(self._terminator)
            if index < 0:
                if len(self._buffer) > self._max:
                    # Keep scanning for the terminator, but this line is already lost.
                    self._overlong = True
                    self._buffer = self._buffer[-len(self._terminator) :]
                return out
            raw, self._buffer = self._buffer[:index], self._buffer[index + len(self._terminator) :]
            if self._overlong or len(raw) > self._max:
                self._overlong = False
                out.append((None, f"a line longer than {self._max} bytes — not a reading"))
                continue
            try:
                out.append((raw.decode(self._encoding), ""))
            except UnicodeDecodeError:
                out.append((None, f"bytes not valid {self._encoding}: {raw[:SNIPPET]!r}"))


def decode_line(channel: Channel, line: str) -> Reading:
    """One text line → a reading through ``channel``'s ascii layout, or a refusal."""
    match = _compiled(channel.layout.pattern).fullmatch(line)
    if match is None:
        raise InvalidReadingError(
            f"{channel.name}: line {_snippet(line)} does not match the profile's pattern."
        )
    if channel.status_field:
        code = match.group(channel.status_field)
        invalid = dict(channel.status_invalid)
        if code in invalid:
            raise InvalidReadingError(f"{channel.name}: status {code!r} ({invalid[code]}).")
        if code not in channel.status_ok:
            raise InvalidReadingError(
                f"{channel.name}: status {code!r} is neither ok nor a known invalid code."
            )
    text = match.group("value")
    if text is None or not _NUMBER.fullmatch(text):
        raise InvalidReadingError(f"{channel.name}: {text!r} is not a number.")
    value = float(text)
    if not math.isfinite(value):
        raise InvalidReadingError(f"{channel.name}: the instrument sent {value}.")
    unit = channel.unit
    if channel.unit_from:
        sent = match.group(channel.unit_from) or ""
        if channel.unit and sent != channel.unit:
            raise InvalidReadingError(
                f"{channel.name}: the line says unit {sent!r}, the profile says {channel.unit!r}."
            )
        unit = sent
    reading = _finish(channel, value)
    return Reading(value=reading.value, unit=unit, band=reading.band)


__all__ = ["SNIPPET", "LineFramer", "decode_line"]
