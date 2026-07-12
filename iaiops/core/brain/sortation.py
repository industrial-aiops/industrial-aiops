"""Sortation performance — read rate, mis-sort and no-read analysis (pure).

The warehouse sorter's health question: *are packages being read and diverted to
the right chute?* From per-sort records (barcode read? assigned chute vs the
chute it actually diverted to) it derives the three rates a DC operator watches —
read rate, no-read rate, mis-sort rate — against typical targets, and ranks the
chutes contributing the most mis-sorts (a jammed diverter, a mis-mapped chute).

Pure function over injected sort records (from a WCS / sorter PLC event log);
read-only and advisory, every rate cited by its counts.
"""

from __future__ import annotations

MAX_ROWS = 50

# Typical DC targets: a well-run sorter reads >99% and mis-sorts <0.5%.
DEFAULT_MAX_NO_READ_PCT = 1.0
DEFAULT_MAX_MISSORT_PCT = 0.5


def sortation_health(
    sorts: list[dict],
    max_no_read_pct: float = DEFAULT_MAX_NO_READ_PCT,
    max_missort_pct: float = DEFAULT_MAX_MISSORT_PCT,
) -> dict:
    """[READ] Read-rate / no-read / mis-sort analysis over sorter divert records.

    ``sorts`` are ``{read (bool), assigned_chute, actual_chute}`` — one per item
    crossing the sorter. Read rate and no-read rate are over all items; mis-sort
    rate is over READ items whose ``actual_chute`` differs from ``assigned_chute``.
    Returns the three rates against their targets, an overall verdict, and the
    chutes contributing the most mis-sorts. Every rate is cited by its counts.
    """
    rows = [s for s in (sorts or []) if isinstance(s, dict)]
    total = len(rows)
    if not total:
        return {"items": 0, "verdict": "insufficient", "readRatePct": None,
                "noReadRatePct": None, "missortRatePct": None, "worstChutes": [], "note": _NOTE}

    reads = [s for s in rows if bool(s.get("read", True))]
    no_reads = total - len(reads)
    missorts = [s for s in reads if _missorted(s)]

    read_rate = _pct(len(reads), total)
    no_read_rate = _pct(no_reads, total)
    missort_rate = _pct(len(missorts), len(reads)) if reads else 0.0

    return {
        "items": total,
        "reads": len(reads),
        "noReads": no_reads,
        "missorts": len(missorts),
        "readRatePct": read_rate,
        "noReadRatePct": no_read_rate,
        "missortRatePct": missort_rate,
        "targets": {"maxNoReadPct": max_no_read_pct, "maxMissortPct": max_missort_pct},
        "verdict": _verdict(no_read_rate, missort_rate, max_no_read_pct, max_missort_pct),
        "worstChutes": _worst_chutes(missorts),
        "note": _NOTE,
    }


_NOTE = (
    "Advisory sortation analysis over injected divert records; rates are cited by "
    "their counts. A high-mis-sort chute points at a jammed diverter or a "
    "mis-mapped chute — verify against the sorter's divert confirmations."
)


def _missorted(sort: dict) -> bool:
    assigned = sort.get("assigned_chute")
    actual = sort.get("actual_chute")
    return assigned is not None and actual is not None and assigned != actual


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100.0, 3) if whole else 0.0


def _verdict(no_read: float, missort: float, max_no_read: float, max_missort: float) -> str:
    if no_read > max_no_read and missort > max_missort:
        return "degraded"
    if no_read > max_no_read:
        return "high_no_read"
    if missort > max_missort:
        return "high_missort"
    return "ok"


def _worst_chutes(missorts: list[dict]) -> list[dict]:
    """Chutes ranked by how many mis-sorts they received (worst first)."""
    counts: dict[str, int] = {}
    for s in missorts:
        chute = str(s.get("actual_chute"))
        counts[chute] = counts.get(chute, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [{"chute": chute, "missorts": n} for chute, n in ranked[:MAX_ROWS]]


__all__ = ["sortation_health", "MAX_ROWS", "DEFAULT_MAX_NO_READ_PCT", "DEFAULT_MAX_MISSORT_PCT"]
