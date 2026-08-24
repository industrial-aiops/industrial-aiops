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


def humanize_seconds(seconds: float) -> str:
    """A duration in the unit that makes it readable at its own scale.

    A week-long run reads naturally in hours; a two-minute one does not, and
    ``f"{s/3600:.1f}h"`` renders ten seconds of blind time as "0.0h" — true, and
    misleading in the direction that makes a gap look like nothing.
    """
    seconds = max(0.0, float(seconds))
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
    if value is None:
        return "—"
    return f"{100.0 * float(value):.{digits}f}%"


def pct_from_percent(value: float | None, digits: int = 1) -> str:
    """An already-0-100 percentage. For ``coverage_pct`` / ``measured_pct``."""
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}%"


__all__ = ["humanize_seconds", "pct_from_fraction", "pct_from_percent"]
