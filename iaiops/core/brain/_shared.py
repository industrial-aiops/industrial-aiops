"""Shared helpers for the ops layer.

``s()`` sanitizes any device-returned text before it reaches the caller (an OT
server's browse names / descriptions are untrusted input that could carry a
prompt-injection payload). ``num()`` coerces an OPC-UA / Modbus value to a float
for threshold classification, returning None for non-numeric values.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.governance import sanitize


def s(value: Any, limit: int = 256) -> str:
    """Sanitize a scalar OT value to a bounded, control-char-free string."""
    return sanitize(str(value if value is not None else ""), limit)


def num(value: Any) -> float | None:
    """Coerce an OT value to float for threshold/anomaly math, else None.

    Booleans are treated as numeric (True=1.0/False=0.0) so digital points can
    be threshold-classified too.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
