"""Which measured stoppages a person explained — and which nobody did.

The run-state tag decides THAT the line stopped and for how long, automatically,
from the declared ``running_when``. It never decides WHY. A status word has no
declared vocabulary of reasons (D16), and the loss ladder already refuses to tell
a breakdown from a changeover on its own (``oee_losses``). The only reasons this
product holds are the ones a person gave with ``iaiops case confirm``.

This module is the join, and its job is to keep one number honest: the share of
stopped time that has a reason. Every way of getting that wrong raises it.

* **A case is not an answer.** ``case open`` attaches what someone DID after a
  stoppage, from the audit trail, and marks the capture ``inferred``. That is a
  recorded fact about actions, not a cause. Only a confirmation or a dismissal —
  a person's decision — moves a stoppage out of "unexplained".
* **An unexamined stoppage is not an unexplained one, nor an explained one.**
  ``measure_availability`` hands back a capped list (longest first). The rest
  are counted as NOT examined, separately, so the classes can neither absorb
  them nor quietly lose them.
* **The join key is the case id, recomputed.** A case for another endpoint, or
  for an onset that does not match a measured stoppage, explains nothing here.

[PURE] No I/O. The caller supplies the measurement and the site's cases.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.knowledge.case_store import case_id
from iaiops.core.runtime.envelope import envelope_fields

#: A person named the cause (``case confirm``).
PERSON_CONFIRMED = "person_confirmed"
#: A person said it was not an incident (``case dismiss``). An answer, not a cause.
PERSON_DISMISSED = "person_dismissed"
#: A case was opened and nobody has answered it — including one that carries
#: audit-trail actions, which are what someone did, not why the line stopped.
AWAITING_PERSON = "awaiting_person"
#: Never put to a person: no case exists for this stoppage.
NO_CASE = "no_case"

ATTRIBUTIONS = (PERSON_CONFIRMED, PERSON_DISMISSED, AWAITING_PERSON, NO_CASE)

#: What detected the stoppages, stated in the result so nobody reads "classified".
DETECTED_BY = "run_state signal (declared running_when) — detects a stop and its duration only"


def _classify(case: Any) -> str:
    if case is None:
        return NO_CASE
    if getattr(case, "label", ""):
        return PERSON_CONFIRMED
    if getattr(case, "answered", False):
        return PERSON_DISMISSED
    return AWAITING_PERSON


def _window_row(window: dict, case: Any, endpoint: str) -> dict:
    attribution = _classify(case)
    answered = attribution in (PERSON_CONFIRMED, PERSON_DISMISSED)
    return {
        "onset": window["onset"],
        "duration_s": float(window["duration_s"]),
        "minor": bool(window.get("minor")),
        "attribution": attribution,
        "case_id": case_id(endpoint, window["onset"]) if case is not None else "",
        "cause": str(getattr(case, "label", "")) if attribution == PERSON_CONFIRMED else "",
        "capture": str(getattr(case, "capture", "")) if attribution == PERSON_CONFIRMED else "",
        "answered_by": str(getattr(case, "answered_by", "")) if answered else "",
        "answered_at": str(getattr(case, "answered_at", "")) if answered else "",
    }


def attribute_stops(measured: Any, endpoint: str, cases: Any = ()) -> dict:
    """[PURE] Sort a measurement's stoppages by who, if anyone, gave a reason.

    ``measured`` is a :func:`~iaiops.core.brain.oee_measure.measure_availability`
    result; ``cases`` are the site's cases (``case_store.list_cases``). Only an
    ``ok`` measurement is attributed — a refused one has no stoppages anybody
    should be reading.

    Returns per-class ``{count, duration_s}``, the per-stoppage rows, and
    ``not_examined`` / ``not_examined_s`` for the stoppages beyond the list.
    The classes plus ``not_examined`` always sum to ``stops``, and their seconds
    to ``stopped_s``.
    """
    if not isinstance(measured, dict) or measured.get("status") != "ok":
        status = measured.get("status", "invalid") if isinstance(measured, dict) else "invalid"
        return {
            "status": "no_measurement",
            "endpoint": endpoint,
            "note": (
                f"No availability was measured ({status}), so no stoppage is attributed. "
                "Attribution inherits its honesty from the measurement."
            ),
        }

    by_id = {c.incident_id: c for c in (cases or ()) if getattr(c, "incident_id", "")}
    windows = list(measured.get("stop_windows") or ())
    rows = [_window_row(w, by_id.get(case_id(endpoint, w["onset"])), endpoint) for w in windows]

    classes = {name: {"count": 0, "duration_s": 0.0} for name in ATTRIBUTIONS}
    for row in rows:
        bucket = classes[row["attribution"]]
        bucket["count"] += 1
        bucket["duration_s"] += row["duration_s"]
    for bucket in classes.values():
        bucket["duration_s"] = round(bucket["duration_s"], 1)

    stops = int(measured.get("stops", len(rows)))
    examined_s = sum(row["duration_s"] for row in rows)
    not_examined = max(stops - len(rows), 0)
    not_examined_s = round(max(float(measured.get("stopped_s", 0.0)) - examined_s, 0.0), 1)
    explained = classes[PERSON_CONFIRMED]["count"]
    return {
        "status": "ok",
        "endpoint": endpoint,
        "detected_by": DETECTED_BY,
        "reasons_from_signal": 0,
        "stops": stops,
        "examined": len(rows),
        "not_examined": not_examined,
        "not_examined_s": not_examined_s if not_examined else 0.0,
        # The standard bounded-return envelope: `windows` is the examined list,
        # `items_total` every stoppage measured.
        **envelope_fields(
            returned=len(rows),
            total=max(stops, len(rows)),
            note=(
                f"{not_examined} shorter stoppage(s) beyond the examined list are in no "
                "class — not examined, neither explained nor unexplained."
            ),
        ),
        "classes": classes,
        "windows": rows,
        "note": (
            f"{stops} stoppage(s) detected from the run-state signal, which gives a stop "
            "and its duration but never a reason. "
            f"{explained} have a cause a person confirmed; "
            f"{classes[PERSON_DISMISSED]['count']} a person dismissed as not an incident; "
            f"{classes[AWAITING_PERSON]['count']} have a case nobody has answered; "
            f"{classes[NO_CASE]['count']} were never put to a person."
            + (
                f" {not_examined} shorter stoppage(s) beyond the examined list were NOT "
                "examined and are in no class."
                if not_examined
                else ""
            )
        ),
    }


__all__ = [
    "ATTRIBUTIONS",
    "AWAITING_PERSON",
    "DETECTED_BY",
    "NO_CASE",
    "PERSON_CONFIRMED",
    "PERSON_DISMISSED",
    "attribute_stops",
]
