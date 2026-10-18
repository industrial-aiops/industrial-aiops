"""Serial ASCII instruments in a sensor profile (HLD §17.4, D54/D55/D58).

A scale, gas analyser or legacy meter sends a text line per reading. The profile
says how to frame the byte stream into lines (``framing``), whether the device
streams (``mode: listen``) or answers one fixed query (``mode: poll`` + ``query``),
and, per channel, a regex that must match the WHOLE line (``layout.pattern``,
with a ``value`` group), optional status codes, and the unit — fixed, from a
group, or both (then they must agree).

The query is part of the profile and nothing else may be sent (D54): commands
that change the instrument (tare, zero, calibrate) are not reads and do not
belong here — bytes cannot say which is which, so the reviewed, versioned
profile is where that responsibility sits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MODES = ("listen", "poll")
ENCODINGS = ("ascii", "latin-1", "utf-8")
MAX_LINE = 4096
MAX_QUERY = 64


@dataclass(frozen=True)
class Framing:
    terminator: str = "\r\n"
    encoding: str = "ascii"
    max_line: int = 256


@dataclass(frozen=True)
class AsciiLayout:
    """A text line, matched in full by ``pattern``; the reading is group ``value``."""

    pattern: str

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(re.compile(self.pattern).groupindex)


def ascii_layout(raw: dict, where: str) -> AsciiLayout:
    from iaiops.core.runtime.sensor.profile import _reject_unknown

    _reject_unknown(raw, ("pattern",), where)
    pattern = raw.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(f"{where}: an ascii layout needs a pattern (a regex for the whole line).")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{where}: pattern does not compile: {exc}") from exc
    if "value" not in compiled.groupindex:
        raise ValueError(f"{where}: pattern needs a named group `value` — the reading.")
    return AsciiLayout(pattern=pattern)


def channel_fields(raw: dict, layout: AsciiLayout, where: str) -> dict[str, Any]:
    """unit / unit_from / status for a serial channel → Channel keyword arguments."""
    unit = raw.get("unit")
    unit_from = raw.get("unit_from")
    if unit is None:
        raise ValueError(
            f"{where}: a serial channel needs a fixed unit (`unit`) — a series that mixes kg "
            "and g is not one series. `unit_from` then only checks each line against it."
        )
    if unit_from is not None and unit_from not in layout.groups:
        raise ValueError(f"{where}: unit_from {unit_from!r} is not a group in the pattern.")
    out: dict[str, Any] = {"unit": "", "unit_from": unit_from or ""}
    if unit is not None:
        from iaiops.core.runtime.sensor.profile import _unit

        out["unit"] = _unit(raw, where)
    status = raw.get("status")
    if status is not None:
        out.update(_status(status, layout, where))
    return out


def _status(raw: Any, layout: AsciiLayout, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - {"field", "ok", "invalid"}:
        raise ValueError(f"{where}: status is {{field, ok: [...], invalid: {{code: meaning}}}}.")
    field = raw.get("field")
    if field not in layout.groups:
        raise ValueError(f"{where}: status field {field!r} is not a group in the pattern.")
    ok = raw.get("ok")
    if not isinstance(ok, list) or not ok or not all(isinstance(c, str) and c for c in ok):
        raise ValueError(f"{where}: status ok must list the code(s) that mean a valid reading.")
    invalid = raw.get("invalid") or {}
    if not isinstance(invalid, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v for k, v in invalid.items()
    ):
        raise ValueError(f"{where}: status invalid maps code → meaning (both text).")
    overlap = sorted(set(ok) & set(invalid))
    if overlap:
        raise ValueError(f"{where}: status code(s) {', '.join(overlap)} are both ok and invalid.")
    return {
        "status_field": field,
        "status_ok": tuple(ok),
        "status_invalid": tuple(sorted(invalid.items())),
    }


def framing(raw: Any, where: str) -> Framing:
    if raw is None:
        return Framing()
    if not isinstance(raw, dict) or set(raw) - {"terminator", "encoding", "max_line"}:
        raise ValueError(f"{where}: framing is {{terminator, encoding, max_line}}.")
    terminator = raw.get("terminator", "\r\n")
    if not isinstance(terminator, str) or not 1 <= len(terminator) <= 4 or not terminator.isascii():
        raise ValueError(
            f'{where}: framing terminator must be 1–4 ASCII characters, e.g. "\\r\\n".'
        )
    encoding = raw.get("encoding", "ascii")
    if encoding not in ENCODINGS:
        raise ValueError(f"{where}: framing encoding must be one of {', '.join(ENCODINGS)}.")
    max_line = raw.get("max_line", 256)
    if isinstance(max_line, bool) or not isinstance(max_line, int) or not 1 <= max_line <= MAX_LINE:
        raise ValueError(f"{where}: framing max_line must be 1..{MAX_LINE}.")
    return Framing(terminator=terminator, encoding=encoding, max_line=max_line)


def mode_and_query(raw: dict, where: str) -> tuple[str, str]:
    mode = raw.get("mode")
    if mode not in MODES:
        raise ValueError(
            f"{where}: mode must be listen (the instrument streams) or poll (it answers a "
            f"query); got {mode!r}. There is no default."
        )
    query = raw.get("query")
    if mode == "listen":
        if query is not None:
            raise ValueError(f"{where}: a listen-mode profile sends nothing — remove the query.")
        return mode, ""
    if not isinstance(query, str) or not query:
        raise ValueError(f"{where}: poll mode needs its query — the one string it may send.")
    printable = all(ch in "\r\n\t" or 0x20 <= ord(ch) < 0x7F for ch in query)
    if len(query) > MAX_QUERY or not printable:
        raise ValueError(
            f"{where}: query must be printable ASCII (plus CR/LF/TAB), at most {MAX_QUERY} "
            "characters."
        )
    return mode, query


__all__ = ["AsciiLayout", "Framing", "ascii_layout", "channel_fields", "framing", "mode_and_query"]
