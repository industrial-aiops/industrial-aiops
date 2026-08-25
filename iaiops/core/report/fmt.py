"""Number and duration formatting shared by the CLI and the HTML reports.

``humanize_seconds`` moved here from ``iaiops/cli/_common.py`` unchanged: the
report needs the identical scale-aware rendering, and ``core`` must not import
from ``cli``. The CLI re-exports it, so every existing caller is untouched.

The percentage helpers are two functions on purpose. ``pct_of_planned`` in the
loss ladder is a FRACTION (0-1) while ``coverage_pct`` and friends are already
percentages (0-100), and rendering one as the other is the easiest mistake on
this page — 25.9% of a shift would print as "0.3%" and nobody would query it.
Separate names make the mix-up visible at the call site instead of in the output.
"""

from __future__ import annotations

import math
from typing import Any

#: What every renderer prints when it does not know. The same dash `cell()` uses,
#: so an unknown reads the same wherever it appears.
UNKNOWN = "—"


def finite(value: Any) -> float | None:
    """A real number, or ``None`` for anything that means "I do not know".

    NaN, ±inf, ``None`` and unparseable text all collapse to ``None`` — because
    they all mean the same thing to a reader, and the alternative is what an audit
    found on 2026-08-25: **NaN walked past every guard in this package**.

    ``min(100.0, nan)`` returns ``100.0``. Every NaN comparison is False, so
    ``min`` keeps its first argument, ``max`` keeps its first argument, and a
    ``<= 0`` guard lets it through. The results, all reproduced:

      * ``meter_svg(nan)`` → a full green bar labelled **100.0%**, on the headline
        availability factor
      * ``stacked_bar_svg(total=nan)`` → an empty chart whose legend claims every
        loss is **100%** of planned time
      * ``humanize_seconds(nan)`` → **"0ms"**, from the very function whose
        docstring warns against "misleading in the direction that makes a gap look
        like nothing"
      * ``pct_from_fraction(nan)`` → **"nan%"** in a customer-facing report

    Every one of those is "we could not compute this" rendered as a confident
    number, and three of the four flatter. That is the defect class this codebase
    exists to refuse, arriving through the one gap a comparison-based guard cannot
    close. So the check is ``math.isfinite``, not a comparison.
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def humanize_seconds(seconds: float) -> str:
    """A duration in the unit that makes it readable at its own scale.

    A week-long run reads naturally in hours; a two-minute one does not, and
    ``f"{s/3600:.1f}h"`` renders ten seconds of blind time as "0.0h" — true, and
    misleading in the direction that makes a gap look like nothing.
    """
    known = finite(seconds)
    if known is None:
        return UNKNOWN
    seconds = max(0.0, known)
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.1f}min"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


def pct_from_fraction(value: float | None, digits: int = 1) -> str:
    """A 0-1 fraction as a percentage. For ``pct_of_planned`` and the factors."""
    known = finite(value)
    return UNKNOWN if known is None else f"{100.0 * known:.{digits}f}%"


def pct_from_percent(value: float | None, digits: int = 1) -> str:
    """An already-0-100 percentage. For ``coverage_pct`` / ``measured_pct``."""
    known = finite(value)
    return UNKNOWN if known is None else f"{known:.{digits}f}%"


def count(value: Any) -> str:
    """A whole number with thousands separators, or the dash.

    ``int(nan)`` raises ``ValueError`` and ``int(inf)`` raises ``OverflowError`` —
    and ``OverflowError`` is not in the CLI's caught families, so it reaches the
    operator as a traceback.
    """
    known = finite(value)
    return UNKNOWN if known is None else f"{int(known):,}"


def total(*values: Any) -> float | None:
    """The sum, or ``None`` if ANY addend is unknown.

    An unknown addend makes the whole sum unknown. Treating it as zero is how
    "we could not see part of this window" becomes "there was no blind time".
    """
    out = 0.0
    for value in values:
        known = finite(value)
        if known is None:
            return None
        out += known
    return out


__all__ = [
    "UNKNOWN",
    "count",
    "finite",
    "humanize_seconds",
    "pct_from_fraction",
    "pct_from_percent",
    "total",
]
