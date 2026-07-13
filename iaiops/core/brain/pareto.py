"""Defect Pareto — the vital few defect categories (pure).

The fab / quality follow-on to an SPC signal: *which defect categories drive most
of the loss?* Pareto's 80/20 — a small number of categories usually account for
the bulk of defects, and those are where containment and CI effort pays off. From
defect records (aggregated counts, or one row per defect) it ranks categories by
count, computes each one's share and the running cumulative share, and marks the
**vital few** that reach the 80 % line.

``defect_pareto`` is pure over injected records; read-only and advisory, every
share cited by its count.
"""

from __future__ import annotations

MAX_ROWS = 100
DEFAULT_VITAL_PCT = 80.0


def defect_pareto(defects: list[dict], vital_pct: float = DEFAULT_VITAL_PCT) -> dict:
    """[READ] Rank defect categories by count and mark the vital few (Pareto 80/20).

    ``defects`` are ``{category, count?}`` — with ``count`` the rows are aggregated
    by category (summing counts); without it each row counts as one occurrence.
    Returns categories count-descending with each one's share and the running
    cumulative share, and the ``vital_few`` categories whose cumulative share first
    reaches ``vital_pct`` (default 80 %). Every share is cited by its count.
    """
    counts = _aggregate(defects)
    total = sum(counts.values())
    if not total:
        return {
            "total_defects": 0,
            "category_count": 0,
            "categories": [],
            "vital_few": [],
            "vital_pct": vital_pct,
            "note": _NOTE,
        }

    ranked = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    rows: list[dict] = []
    cumulative = 0
    vital_reached = False
    for category, count in ranked:
        cumulative += count
        cum_pct = round(cumulative / total * 100.0, 2)
        is_vital = not vital_reached
        if cum_pct >= vital_pct:
            vital_reached = True  # this row crosses the line; later rows are the trivial many
        rows.append(
            {
                "category": category,
                "count": count,
                "pct": round(count / total * 100.0, 2),
                "cumulativePct": cum_pct,
                "vitalFew": is_vital,
            }
        )
    return {
        "total_defects": total,
        "category_count": len(rows),
        "categories": rows[:MAX_ROWS],
        "vital_few": [r["category"] for r in rows if r["vitalFew"]],
        "vital_pct": vital_pct,
        "note": _NOTE,
    }


_NOTE = (
    "Advisory defect Pareto over injected records; each share is cited by its "
    "count. The vital-few categories (to the 80% line) are where containment and "
    "continuous-improvement effort has the most leverage."
)


def _aggregate(defects: list[dict]) -> dict[str, int]:
    """Sum counts per category (count field), else one per record."""
    counts: dict[str, int] = {}
    for d in defects or []:
        if not isinstance(d, dict):
            continue
        category = d.get("category") or d.get("defect_code") or d.get("code")
        if not category:
            continue
        raw = d.get("count", 1)
        n = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 1
        counts[str(category)] = counts.get(str(category), 0) + max(0, n)
    return counts


__all__ = ["defect_pareto", "MAX_ROWS", "DEFAULT_VITAL_PCT"]
