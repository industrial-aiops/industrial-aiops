"""Shared helpers for the ops layer.

``s()`` sanitizes any device-returned text before it reaches the caller (an OT
server's browse names / descriptions are untrusted input that could carry a
prompt-injection payload). ``num()`` coerces an OPC-UA / Modbus value to a float
for threshold classification, returning None for anything that is not a real
number — which includes NaN and ±inf, because they mean "no valid value".
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from iaiops.core.governance import sanitize


def s(value: Any, limit: int = 256) -> str:
    """Sanitize a scalar OT value to a bounded, control-char-free string."""
    return sanitize(str(value if value is not None else ""), limit)


def num(value: Any) -> float | None:
    """Coerce an OT value to float for threshold/anomaly math, else None.

    Booleans are treated as numeric (True=1.0/False=0.0) so digital points can
    be threshold-classified too.

    **NaN and ±inf are not numbers here — they are None.** They arrive from real
    devices (an OPC-UA server returning NaN for a bad float is ordinary), they
    are instances of ``float``, and every comparison against them is False. That
    combination walked them past every guard in this layer, exactly as it had in
    the rendering layer before ``core/report/fmt.finite`` was written for it:

      * ``statistics.pstdev`` refuses non-finite data, so one NaN sample crashed
        ``tag_health`` — and ``downtime_rca`` calls it;
      * ``learn_baseline`` returned ``status: "ok"`` with a band of NaN, which
        every later reading compares "inside", silently ending alerting on that
        tag;
      * the isolation-room, medical-gas, OR-envelope and finished-water checks
        each graded a NaN reading **compliant**.

    "I could not read this" must not render as "this is fine", so it renders as
    nothing at all and the caller's existing missing-value branch handles it.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerant of a trailing Z), else None.

    **Naive timestamps are coerced to UTC.** A device that reports a bare
    ``2026-08-25T10:00:01`` and one that reports ``...Z`` land in the same store —
    ``sqlite_local._normalize_ts`` preserves whatever arrived, and falls back to an
    AWARE ``now()`` when the timestamp is empty. Sorting or subtracting that mix
    without coercion raises ``can't compare offset-naive and offset-aware
    datetimes``, which is a ``TypeError`` — a family the CLI's error harness does
    not catch, so it reaches the operator as a traceback.

    This lived in four places: two copies coerced (``oee._parse_ts``,
    ``diagnostics._parse_ts``, byte-identical apart from their docstrings) and two
    did not (``oee_measure._parse``, ``oee_production._parse``). Both of the
    latter crashed on a store a real plant produces. One implementation now.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
