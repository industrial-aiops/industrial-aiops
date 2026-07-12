"""Downtime triage copilot — one call that composes the three downtime lenses.

An operator facing a stopped line asks three questions at once: *what stopped
it, which alarm do I look at first, and did anything warn us beforehand?* Each
already has a dedicated analysis:

  * :func:`iaiops.core.brain.rca.downtime_rca` — the causal verdict (ranked,
    cited hypotheses).
  * :func:`iaiops.core.brain.alarm_flood.alarm_cascade` — the transparent
    first-out root of the biggest alarm cascade ("look here first").
  * :func:`iaiops.core.brain.pdm.pdm_forecast` — trend/ETA per signal, which
    surfaces precursors that were degrading *before* the trip.

``downtime_triage`` runs all three over one incident and synthesises a single
triage: the first alarm to look at, the likely cause, a **cross-check** of
whether those two agree, and the precursor signals that warned in advance. It
is a pure composition (no I/O) — every field traces to one of the sub-reports,
which are echoed for drill-down. Advisory only; nothing is executed.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain.alarm_flood import alarm_cascade
from iaiops.core.brain.pdm import pdm_forecast
from iaiops.core.brain.rca import DEFAULT_LEAD_WINDOW_S, downtime_rca

# Bounds on the drill-down sub-reports so one call can never balloon.
MAX_HYPOTHESES = 3
MAX_PRECURSORS = 5

# pdm_forecast statuses that count as a pre-incident warning.
_PRECURSOR_STATUSES = frozenset({"imminent", "degrading"})

_AH_NOTE = (
    "Advisory triage composed from the alarm cascade, the RCA verdict, and PdM "
    "forecasts — only signals present in the input are cited; nothing is executed."
)


def downtime_triage(
    window: dict[str, Any],
    alarms: list[dict] | None = None,
    tags: list[dict] | None = None,
    dataflow: dict | None = None,
    state_series: list[dict] | None = None,
    precursors: list[dict] | None = None,
    cascade_window_s: float = 60.0,
    lead_window_s: float = DEFAULT_LEAD_WINDOW_S,
    cause_weights: dict[str, float] | None = None,
    historian: dict | None = None,
    imminent_within_s: float = 86_400.0,
) -> dict:
    """[READ] Compose the alarm cascade, RCA verdict, and PdM precursors into one triage.

    ``window`` is ``{start, end?, asset?, category?}`` (as for ``downtime_rca``).
    ``alarms`` feeds BOTH the cascade (first-out root) and the RCA. ``precursors``
    is a list of ``{signal, series, warn_high?, alarm_high?, warn_low?,
    alarm_low?}`` — each series is run through ``pdm_forecast`` and kept only when
    it was degrading/imminent (a warning that preceded the trip). Sub-reports are
    echoed under ``cascade`` / ``rca`` / ``precursor_forecasts`` for drill-down.
    """
    rca = downtime_rca(
        window, alarms, tags, dataflow, state_series, lead_window_s, cause_weights,
        historian=historian,
    )
    cascade = alarm_cascade(alarms or [], window_s=cascade_window_s)
    flagged = _forecast_precursors(precursors, imminent_within_s)

    first_look = _first_look(cascade)
    likely_cause = _likely_cause(rca)
    cross_check = _cross_check(first_look, rca)

    return {
        "window": rca.get("window"),
        "triage": {
            "first_look": first_look,
            "likely_cause": likely_cause,
            "cross_check": cross_check,
            "precursors_missed": flagged[:MAX_PRECURSORS],
            "recommended_next_data": rca.get("recommended_next_data", []),
        },
        "cascade": _cascade_summary(cascade),
        "rca": _rca_summary(rca),
        "precursor_forecasts": flagged[:MAX_PRECURSORS],
        "anti_hallucination": _AH_NOTE,
    }


def _forecast_precursors(precursors: list[dict] | None, imminent_within_s: float) -> list[dict]:
    """Run each precursor series through pdm_forecast; keep only the ones that warned."""
    flagged: list[dict] = []
    for p in precursors or []:
        if not isinstance(p, dict) or not p.get("series"):
            continue
        fc = pdm_forecast(
            p["series"],
            warn_high=p.get("warn_high"), alarm_high=p.get("alarm_high"),
            warn_low=p.get("warn_low"), alarm_low=p.get("alarm_low"),
            imminent_within_s=imminent_within_s,
        )
        if fc.get("status") in _PRECURSOR_STATUSES:
            flagged.append({
                "signal": p.get("signal"),
                "status": fc.get("status"),
                "direction": fc.get("direction"),
                "eta_to_limit": fc.get("eta_to_limit"),
                "unit": fc.get("unit"),
                "limit": fc.get("limit"),
            })
    flagged.sort(key=lambda f: (f["status"] != "imminent", _eta_key(f)))
    return flagged


def _eta_key(f: dict) -> float:
    """Sort key: soonest ETA first; missing ETA sinks to the bottom."""
    eta = f.get("eta_to_limit")
    return float(eta) if isinstance(eta, (int, float)) else float("inf")


def _first_look(cascade: dict) -> dict | None:
    """The first-out root of the biggest cascade — the alarm to look at first."""
    cascades = cascade.get("cascades") or []
    if not cascades:
        return None
    biggest = cascades[0]  # alarm_cascade sorts cascades by size desc
    root = biggest.get("root") or {}
    return {
        "source": root.get("source"),
        "ts": root.get("ts"),
        "cascade_size": biggest.get("size"),
        "basis": "first-out alarm (earliest in the biggest cascade) — heuristic, not causal",
    }


def _likely_cause(rca: dict) -> dict | None:
    """The RCA's primary cause, flattened from its primary hypothesis dict.

    ``downtime_rca`` returns ``primary_cause`` as the winning hypothesis dict
    (``{cause, confidence, confidence_band, evidence, recommended_action}``) or
    None — not a bare cause string.
    """
    primary = rca.get("primary_cause")
    if not isinstance(primary, dict):
        return None
    return {
        "cause": primary.get("cause"),
        "verdict": rca.get("verdict"),
        "confidence": primary.get("confidence"),
        "confidence_band": primary.get("confidence_band"),
        "recommended_action": primary.get("recommended_action"),
    }


def _cross_check(first_look: dict | None, rca: dict) -> dict:
    """Does the first-out alarm appear among the RCA primary cause's evidence?

    Best-effort corroboration: if the alarm the operator is told to look at first
    is also cited by the causal verdict, the two lenses agree ("corroborated");
    if the RCA leans elsewhere, they diverge (worth a second look). Never a hard
    claim — it only reports whether the signals line up.
    """
    if not first_look or not first_look.get("source"):
        return {"status": "no_alarm_root", "detail": "No alarm cascade to cross-check."}
    primary = rca.get("primary_cause")
    if not isinstance(primary, dict):
        return {"status": "no_rca_primary", "detail": "RCA reached no primary cause."}
    cited = _evidence_strings(primary)
    source = str(first_look["source"])
    cause = primary.get("cause")
    if source in cited:
        return {"status": "corroborated",
                "detail": f"First-out alarm '{source}' is cited by RCA cause '{cause}'."}
    return {"status": "diverging",
            "detail": f"First-out alarm '{source}' is not among RCA cause '{cause}' evidence."}


def _evidence_strings(hypothesis: dict | None) -> set[str]:
    """Collect the ref/signal strings a hypothesis cites, for the cross-check."""
    cited: set[str] = set()
    for ev in ((hypothesis or {}).get("evidence") or []):
        for key in ("ref", "signal", "source"):
            value = ev.get(key)
            if value:
                cited.add(str(value))
    return cited


def _cascade_summary(cascade: dict) -> dict:
    cascades = cascade.get("cascades") or []
    return {
        "cascade_count": cascade.get("cascade_count", 0),
        "total_activations": cascade.get("total_activations", 0),
        "biggest_cascade_size": cascades[0].get("size") if cascades else 0,
    }


def _rca_summary(rca: dict) -> dict:
    return {
        "verdict": rca.get("verdict"),
        "primary_cause": rca.get("primary_cause"),
        "top_hypotheses": (rca.get("hypotheses") or [])[:MAX_HYPOTHESES],
    }


__all__ = ["downtime_triage", "MAX_HYPOTHESES", "MAX_PRECURSORS"]
