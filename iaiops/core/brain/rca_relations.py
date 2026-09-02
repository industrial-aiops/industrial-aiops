"""Which stoppage was the origin, and which ones were just downstream of it.

`_proximity_scale` weights evidence by TIME alone: a signal before onset counts,
one after it counts less. That is the right rule and only half the axis. Run
`downtime_rca` for each asset on a line after one upstream stop and every
downstream asset comes back with its own confident local root cause — each
verdict internally consistent, each citing real signals, and all but one of them
about a machine that stopped because it was starved, not because anything was
wrong with it. Nothing in the evidence distinguishes those cases, because the
distinguishing fact is not in the evidence: it is the line's topology.

So the topology is asked for, and it is **declared, never inferred** (D25).
Co-occurrence on a production line is guaranteed — every machine stops together —
so mining it for edges would manufacture exactly the causality this module exists
to remove. With no declared relations the answer is "not evaluable", not a guess.

Two rules decide an attribution, and both must hold:

* **direction** — the candidate origin must be declared upstream of the asset;
* **order** — it must have stopped first. An upstream stop that began *after* a
  downstream one cannot have caused it, however upstream it is. Time was already
  the honest half of the axis and it stays.

The output is per stoppage, because that is the shape of the problem: one origin,
a set of consequences, and anything the declared topology cannot connect left
explicitly unattributed rather than swept into the origin's column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import parse_ts, s
from iaiops.core.knowledge.relations import downstream_of, line_relations

MAX_STOPPAGES = 500

#: A downstream stop is attributed to an upstream one only if it began within
#: this long after it. Beyond that the line has usually recovered or been
#: restarted, and the two are separate events that happen to share a shift.
DEFAULT_MAX_LEAD_S = 900.0

ORIGIN = "origin"
CONSEQUENCE = "consequence_of_upstream"
UNATTRIBUTED = "unattributed"
NOT_EVALUABLE = "not_evaluable"

_NO_RELATIONS = (
    "No line relations are declared for this site, so nothing here can tell an "
    "origin from a consequence. Declare the order with `iaiops relations declare "
    "--upstream A --downstream B`. Co-occurrence is NOT used as a substitute: on a "
    "production line everything stops together, so mining it for edges would "
    "manufacture the causality this check exists to remove (D25)."
)


def _rows(stoppages: Any) -> list[dict]:
    """Validated ``{asset, start, _dt}`` rows, earliest first."""
    if not isinstance(stoppages, list):
        raise ValueError("stoppages must be a list of {asset, start, end?} rows.")
    out: list[dict] = []
    for raw in stoppages[:MAX_STOPPAGES]:
        if not isinstance(raw, dict):
            continue
        asset = s(raw.get("asset", raw.get("line", "")), 96).strip()
        started = parse_ts(raw.get("start", raw.get("ts", raw.get("timestamp"))))
        if not asset or started is None:
            continue
        out.append({"asset": asset, "start": raw.get("start", raw.get("ts")), "_dt": started})
    out.sort(key=lambda r: r["_dt"])
    return out


def _origin_for(
    row: dict,
    rows: list[dict],
    reach: dict[str, tuple[str, ...]],
    max_lead_s: float,
) -> dict | None:
    """The nearest declared-upstream stoppage that began first, if any."""
    best: dict | None = None
    for other in rows:
        if other is row or other["asset"] == row["asset"]:
            continue
        path = reach.get(other["asset"], ())
        if row["asset"] not in path:
            continue  # not declared upstream of this asset
        lead = (row["_dt"] - other["_dt"]).total_seconds()
        if lead < 0 or lead > max_lead_s:
            continue  # began after it, or too far apart to be the same event
        hops = path.index(row["asset"]) + 1
        rank = (hops, lead)
        if best is None or rank < best["_rank"]:
            best = {
                "_rank": rank,
                "asset": other["asset"],
                "start": other["start"],
                "hops_upstream": hops,
                "lead_s": round(lead, 3),
            }
    return best


def attribute_downtime(
    stoppages: list[dict],
    site: str = "default",
    max_lead_s: float = DEFAULT_MAX_LEAD_S,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """[READ] Separate the stoppage that started it from the ones that followed.

    ``stoppages`` are ``{asset, start, end?}`` rows for one incident window.
    Attribution needs a declared line order and correct time order; without
    relations every row is ``not_evaluable`` and the reason says how to fix that.
    """
    rows = _rows(stoppages)
    relations = line_relations(site, base_dir)
    if not relations:
        return {
            "site": site,
            "stoppages_evaluated": len(rows),
            "relations_declared": 0,
            "verdict": NOT_EVALUABLE,
            "attributions": [
                {"asset": r["asset"], "start": r["start"], "status": NOT_EVALUABLE} for r in rows
            ],
            "reason": _NO_RELATIONS,
        }

    reach = {r["asset"]: downstream_of(r["asset"], site, base_dir) for r in rows}
    attributions = []
    for row in rows:
        origin = _origin_for(row, rows, reach, max_lead_s)
        if origin is None:
            downstream_here = [o for o in rows if o["asset"] in reach.get(row["asset"], ())]
            attributions.append(
                {
                    "asset": row["asset"],
                    "start": row["start"],
                    "status": ORIGIN if downstream_here else UNATTRIBUTED,
                    "explains": [o["asset"] for o in downstream_here],
                    "detail": (
                        f"stopped first and is declared upstream of "
                        f"{len(downstream_here)} other stopped asset(s)"
                        if downstream_here
                        else "no declared upstream asset stopped before it within the window"
                    ),
                }
            )
        else:
            attributions.append(
                {
                    "asset": row["asset"],
                    "start": row["start"],
                    "status": CONSEQUENCE,
                    "origin_asset": origin["asset"],
                    "origin_start": origin["start"],
                    "hops_upstream": origin["hops_upstream"],
                    "lead_s": origin["lead_s"],
                    "detail": (
                        f"{origin['asset']} is declared {origin['hops_upstream']} hop(s) upstream "
                        f"and stopped {origin['lead_s']}s earlier — a local root cause here is a "
                        "consequence unless it precedes that stop"
                    ),
                }
            )

    origins = [a["asset"] for a in attributions if a["status"] == ORIGIN]
    consequences = [a for a in attributions if a["status"] == CONSEQUENCE]
    return {
        "site": site,
        "stoppages_evaluated": len(rows),
        "relations_declared": len(relations),
        "max_lead_s": max_lead_s,
        "verdict": ORIGIN if len(origins) == 1 else "multiple_origins" if origins else UNATTRIBUTED,
        "origins": origins,
        "consequence_count": len(consequences),
        "attributions": attributions,
        "advisory": (
            "Direction comes from declared relations, order from timestamps, and BOTH must "
            "hold — an upstream asset that stopped later cannot have caused an earlier stop. "
            "Assets the declared topology does not connect are left unattributed rather than "
            "assigned to the origin. Advisory: this ranks the stoppages, it does not diagnose "
            "the origin — run downtime_rca on the origin asset for that."
        ),
    }


__all__ = [
    "CONSEQUENCE",
    "DEFAULT_MAX_LEAD_S",
    "NOT_EVALUABLE",
    "ORIGIN",
    "UNATTRIBUTED",
    "attribute_downtime",
]
