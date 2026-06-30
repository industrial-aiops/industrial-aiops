"""AI downtime root-cause copilot — cross-protocol correlation, READ-ONLY.

The flagship intelligence layer: given a downtime/incident window and whatever
evidence the site can hand over (alarm events, tag samples, a dataflow verdict,
a machine-state series), it correlates the streams *in time*, ranks candidate
root causes, and emits an **evidence-cited** verdict plus an **advisory**
(human-approved, undoable) recommended action.

Design stance (non-negotiable):

  * **Read-first / advisory only.** This module never writes, never executes an
    action. It *proposes* a reversible, MOC-gated action; a human approves it and
    a separate (HIGH risk_tier) write tool performs it with undo capture.
  * **Anti-hallucination.** Every citation references a signal that is actually
    present in the input (an alarm's real source+timestamp, a tag's real flag, a
    real dataflow verdict). Nothing is invented. When evidence is thin the verdict
    downgrades to ``insufficient_evidence`` and lists what to collect next — it
    does not guess a cause to look confident.
  * **Pure / injectable.** Like the rest of the brain, it analyzes *provided*
    evidence, so it is fully testable without a live plant. It reuses the existing
    analyzers (``alarm_bad_actors``, ``tag_health``, ``downtime_events``) rather
    than re-deriving them.

Confidence combines independent evidence with a noisy-OR (``1 - Π(1-wᵢ)``), so
agreement across streams compounds toward — but never reaches — certainty, and a
single weak signal stays weak. Temporal proximity to onset scales each weight: a
cause precedes its effect, so a signal just *before* the stoppage outweighs one
*during* it, and signals *after* onset are treated as consequences, not causes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.brain.diagnostics import (
    MAX_EVENTS,
    MAX_SERIES,
    _parse_ts,
    alarm_bad_actors,
    tag_health,
)
from iaiops.core.brain.oee import downtime_events

# How far before onset a signal may sit and still count as a *cause* candidate.
DEFAULT_LEAD_WINDOW_S = 300.0
# Confidence bands over the noisy-OR aggregate.
HIGH_CONFIDENCE = 0.7
MEDIUM_CONFIDENCE = 0.4
# A primary must beat the runner-up by this margin to read as "the" root cause.
DOMINANCE_MARGIN = 0.2

# Per-site cause-weight multipliers. ``downtime_rca`` multiplies every piece of
# evidence for a cause by its multiplier before noisy-OR aggregation, so a site
# can up-/down-weight causes it has learned to trust more/less. 1.0 is neutral
# (the shipped behaviour); overrides are clamped to [MIN, MAX] at the boundary.
DEFAULT_CAUSE_WEIGHT = 1.0
MIN_CAUSE_WEIGHT = 0.1
MAX_CAUSE_WEIGHT = 3.0

# Per-evidence base support (∈[0,1)) before the proximity scale is applied.
# Tuned so no single signal alone reaches HIGH — corroboration is what earns it.
W_DATAFLOW_CANNOT_CONNECT = 0.6
W_DATAFLOW_STALE_OR_FLATLINE = 0.45
W_DATAFLOW_BAD_QUALITY = 0.4
W_ALARM_TRIGGER = 0.5
W_ALARM_FLOOD_CONTEXT = 0.2
W_TAG_SEVERE = 0.45
W_TAG_MINOR = 0.2
W_DOWNTIME_CATEGORY_PRIOR = 0.25

# Stoppage / alarm text → a cause category. Ordered: first hit wins.
CAUSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mechanical_fault": ("fault", "jam", "mechanical", "breakdown", "estop",
                         "e-stop", "trip", "motor", "drive", "overload", "bearing"),
    "comms_loss": ("comm", "comms", "timeout", "disconnect", "offline", "network",
                   "heartbeat", "link"),
    "sensor_fault": ("sensor", "transmitter", "probe", "stuck", "flatline",
                     "bad quality", "signal"),
    "material_starvation": ("material", "starved", "starve", "blocked", "no part",
                            "feed", "infeed", "empty", "level low"),
    "quality_reject": ("quality", "reject", "scrap", "defect", "out of spec",
                       "tolerance"),
    "changeover": ("changeover", "setup", "product change", "tool change", "recipe"),
    "utility_fault": ("power", "air", "vacuum", "coolant", "hydraulic", "pneumatic",
                      "utility", "supply"),
}

# Every cause the copilot can attribute, including the ``alarm_flood`` context tag.
# A ``cause_weights`` override may only name a member of this set.
KNOWN_CAUSES: frozenset[str] = frozenset(CAUSE_KEYWORDS) | {"alarm_flood"}

# Advisory, reversible, MOC-gated next step per cause. Never executed here.
RECOMMENDED_ACTIONS: dict[str, str] = {
    "mechanical_fault": "Dispatch maintenance to inspect the faulting unit; if a "
    "latch/interlock is set, the reversible step is to clear the fault and reset "
    "the latch (MOC-approved, undo captures the prior latch state).",
    "comms_loss": "Check the network path / PLC-agent before any control action. "
    "The reversible step is to restart the comms driver or re-establish the "
    "session — no field state changes.",
    "sensor_fault": "Field-verify the sensor/transmitter and wiring. The reversible "
    "step is to flag the tag bad-quality / switch to a redundant source; do NOT "
    "force the value on a live control loop.",
    "material_starvation": "Replenish/clear the upstream feed. The reversible step "
    "is an operator infeed reset once material is confirmed present.",
    "quality_reject": "Review the rejecting station's setpoints against the recipe. "
    "Any setpoint change is HIGH risk_tier, MOC-gated, and undo-captured.",
    "changeover": "Confirm the changeover/recipe load completed. The reversible step "
    "is to re-issue or roll back the recipe selection (undo captures the prior recipe).",
    "utility_fault": "Confirm the utility (power/air/coolant) is restored at source "
    "before restart. No control write until the utility reads nominal.",
    "alarm_flood": "An alarm flood is masking the trigger. Apply ISA-18.2 shelving / "
    "rationalization to the chattering/standing offenders, then re-run the copilot "
    "on the quieted window.",
    "unknown": "Evidence does not localize a single cause. Collect the data listed "
    "in 'recommended_next_data' and re-run before any control action.",
}


def downtime_rca(
    window: dict[str, Any],
    alarms: list[dict] | None = None,
    tags: list[dict] | None = None,
    dataflow: dict | None = None,
    state_series: list[dict] | None = None,
    lead_window_s: float = DEFAULT_LEAD_WINDOW_S,
    cause_weights: dict[str, float] | None = None,
) -> dict:
    """[READ] Correlate evidence around a downtime window into a cited root cause.

    ``window`` is ``{start, end?, asset?, category?}`` (ISO-8601 timestamps); if
    ``end`` is omitted but a ``state_series`` is given, the first running→stopped
    span is used to bound the incident. Each evidence stream is optional — the
    copilot scores whatever is provided and is explicit about what is missing.

    ``cause_weights`` is an optional per-site ``{cause: multiplier}`` override
    (e.g. from ``learn_cause_weights``): each cause's evidence is scaled by its
    multiplier (1.0 = neutral, today's behaviour) before the noisy-OR, so a site
    can up-/down-weight causes its history has shown to be more/less reliable.
    Unknown causes or non-numeric weights raise; values are clamped to
    ``[MIN_CAUSE_WEIGHT, MAX_CAUSE_WEIGHT]``. Absent ⇒ no behaviour change.

    Returns a structured verdict: ranked ``hypotheses`` (each with a confidence,
    band, and real-signal ``evidence`` citations + an advisory action),
    ``primary_cause``, an ``evidence_summary``, and — when thin —
    ``recommended_next_data``. Nothing is executed; all actions are advisory.
    """
    weights = _normalize_cause_weights(cause_weights)
    win = _resolve_window(window, state_series)
    if "error" in win:
        return {"verdict": "insufficient_evidence", **win,
                "anti_hallucination": _AH_NOTE}

    onset = win["_onset"]
    lead = max(0.0, float(lead_window_s))

    contributions: dict[str, list[dict]] = {}
    _score_dataflow(dataflow, contributions)
    alarm_ctx = _score_alarms(alarms, onset, lead, win["end_dt"], contributions)
    _score_tags(tags, contributions)
    _score_category_prior(win.get("category"), contributions)

    contributions = _apply_cause_weights(contributions, weights)
    hypotheses = _build_hypotheses(contributions)
    verdict, primary = _decide(hypotheses)
    summary = _evidence_summary(alarm_ctx, tags, dataflow, contributions)
    out = {
        "window": {k: win[k] for k in ("start", "end", "duration_s", "asset", "category")},
        "verdict": verdict,
        "primary_cause": primary,
        "hypotheses": hypotheses,
        "evidence_summary": summary,
        "anti_hallucination": _AH_NOTE,
    }
    if verdict == "insufficient_evidence":
        out["recommended_next_data"] = _next_data(alarm_ctx, tags, dataflow)
    return out


_AH_NOTE = (
    "Advisory only — nothing is executed. Every cited signal is present in the "
    "supplied evidence (no fabricated readings); confidence reflects how much real, "
    "time-correlated evidence agrees. Low confidence means thin evidence, not a "
    "ruled-out fault. Any action is human-approved, MOC-gated, and undoable."
)


# ─── window resolution ───────────────────────────────────────────────────────


def _resolve_window(window: dict[str, Any], state_series: list[dict] | None) -> dict:
    """Normalize the incident window; derive ``end`` from a state series if absent."""
    if not isinstance(window, dict):
        return {"error": "window must be {start, end?, asset?, category?}."}
    onset = _parse_ts(window.get("start"))
    if onset is None:
        return {"error": "window.start must be an ISO-8601 timestamp."}
    end_dt = _parse_ts(window.get("end"))
    category = window.get("category")
    if end_dt is None and state_series:
        derived = _first_stoppage(state_series)
        if derived:
            onset = onset or derived["_onset"]
            end_dt = derived["end_dt"]
            category = category or derived.get("category")
    if end_dt is not None and end_dt < onset:
        return {"error": "window.end is before window.start — check the incident times."}
    duration = round((end_dt - onset).total_seconds(), 3) if end_dt else None
    return {
        "start": s(str(onset), 40),
        "end": s(str(end_dt), 40) if end_dt else None,
        "duration_s": duration,
        "asset": s(str(window.get("asset", "")), 64),
        "category": s(str(category), 32) if category else None,
        "_onset": onset,
        "end_dt": end_dt,
    }


def _first_stoppage(state_series: list[dict]) -> dict | None:
    """Bound the incident from the first running→stopped span in a state series."""
    ev = downtime_events(list(state_series or [])[:MAX_SERIES])
    events = ev.get("events") or []
    if not events:
        return None
    first = events[0]
    return {
        "_onset": _parse_ts(first.get("start")),
        "end_dt": _parse_ts(first.get("end")),
        "category": first.get("category"),
    }


# ─── per-site cause weighting ────────────────────────────────────────────────


def _normalize_cause_weights(cause_weights: dict[str, float] | None) -> dict[str, float]:
    """Validate + clamp a per-site ``{cause: multiplier}`` override at the boundary.

    Returns a NEW dict (never mutates the input) holding only non-neutral, known
    causes. ``None``/empty ⇒ ``{}`` (no behaviour change). Teaches on unknown
    causes or non-numeric weights rather than silently dropping them.
    """
    if not cause_weights:
        return {}
    if not isinstance(cause_weights, dict):
        raise ValueError(
            "cause_weights must be a {cause: weight} mapping, e.g. "
            "{'mechanical_fault': 1.5}."
        )
    normalized: dict[str, float] = {}
    for cause, raw in cause_weights.items():
        if cause not in KNOWN_CAUSES:
            raise ValueError(
                f"cause_weights[{cause!r}] is not a known cause; valid causes: "
                f"{sorted(KNOWN_CAUSES)}."
            )
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"cause_weights[{cause!r}] must be a number (got {raw!r})."
            ) from exc
        normalized[cause] = max(MIN_CAUSE_WEIGHT, min(value, MAX_CAUSE_WEIGHT))
    return normalized


def _apply_cause_weights(
    contributions: dict[str, list[dict]], weights: dict[str, float]
) -> dict[str, list[dict]]:
    """Scale each cause's evidence by its per-site multiplier (immutably).

    Returns a NEW contributions map; weights are re-clamped to the same [0,0.95]
    band ``_add`` enforces so a boost can never manufacture certainty.
    """
    if not weights:
        return contributions
    scaled: dict[str, list[dict]] = {}
    for cause, items in contributions.items():
        mult = weights.get(cause, DEFAULT_CAUSE_WEIGHT)
        if mult == DEFAULT_CAUSE_WEIGHT:
            scaled[cause] = items
            continue
        scaled[cause] = [
            {**it, "weight": round(max(0.0, min(it["weight"] * mult, 0.95)), 4)}
            for it in items
        ]
    return scaled


# ─── per-stream scoring ──────────────────────────────────────────────────────


def _add(contributions: dict[str, list[dict]], cause: str, weight: float, cite: dict) -> None:
    """Record one (bounded) piece of support for ``cause`` with its citation."""
    w = max(0.0, min(float(weight), 0.95))
    if w <= 0.0:
        return
    contributions.setdefault(cause, []).append({"weight": round(w, 4), **cite})


def _proximity_scale(at: datetime | None, onset: datetime, lead: float) -> float:
    """Weight multiplier by how a signal sits relative to onset (cause precedes effect)."""
    if at is None:
        return 0.6  # untimed evidence: real but not time-localized
    lead_s = (onset - at).total_seconds()  # >0 ⇒ before onset
    if lead_s < 0:
        return 0.25  # after onset → likely a consequence, not the cause
    if lead == 0:
        return 1.0 if lead_s == 0 else 0.5
    if lead_s > lead:
        return 0.3  # before, but outside the causal lead window
    # Closer to onset within the lead window ⇒ stronger (1.0 → ~0.6).
    return round(1.0 - 0.4 * (lead_s / lead), 4)


def _score_dataflow(dataflow: dict | None, contributions: dict[str, list[dict]]) -> None:
    """Map a diagnose_dataflow verdict to a cause contribution."""
    if not isinstance(dataflow, dict):
        return
    verdict = str(dataflow.get("verdict", "")).strip()
    if not verdict or verdict == "healthy":
        return
    mapping = {
        "cannot_connect": ("comms_loss", W_DATAFLOW_CANNOT_CONNECT),
        "comms_ok_value_unreadable": ("comms_loss", W_DATAFLOW_BAD_QUALITY),
        "comms_ok_bad_quality": ("sensor_fault", W_DATAFLOW_BAD_QUALITY),
        "comms_ok_value_stale": ("sensor_fault", W_DATAFLOW_STALE_OR_FLATLINE),
        "comms_ok_flatline": ("sensor_fault", W_DATAFLOW_STALE_OR_FLATLINE),
    }
    if verdict not in mapping:
        return
    cause, weight = mapping[verdict]
    _add(contributions, cause, weight, {
        "signal": "dataflow",
        "ref": s(verdict, 48),
        "detail": s(str(dataflow.get("diagnosis", "")), 200),
    })


def _score_alarms(
    alarms: list[dict] | None,
    onset: datetime,
    lead: float,
    end_dt: datetime | None,
    contributions: dict[str, list[dict]],
) -> dict:
    """Correlate alarm events to causes by category + temporal proximity to onset."""
    evts = [e for e in (alarms or [])[:MAX_EVENTS] if isinstance(e, dict)]
    if not evts:
        return {"count": 0}
    flood = alarm_bad_actors(evts)
    if isinstance(flood, dict) and flood.get("flood_verdict") == "flood":
        _add(contributions, "alarm_flood", W_ALARM_FLOOD_CONTEXT, {
            "signal": "alarm_rate",
            "ref": "flood",
            "detail": s(f"{flood.get('alarms_per_hour')} alarms/hour (ISA-18.2 flood)", 120),
        })
    horizon = end_dt or onset
    # Dedupe per (source, cause): a single source chattering N times is ONE piece
    # of evidence, not N independent ones — keep only its strongest (closest to
    # onset) hit so noisy-OR can't manufacture confidence from a repeating alarm.
    best: dict[tuple[str, str], dict] = {}
    for e in evts:
        at = _parse_ts(e.get("timestamp"))
        # Only alarms up to the incident horizon can be a trigger; later = noise.
        if at is not None and at > horizon:
            continue
        source = s(str(e.get("source", e.get("tag", "unknown"))), 96)
        label = str(e.get("source", e.get("tag", ""))) + " " + str(e.get("message", ""))
        cause = _classify_text(label)
        if cause == "unknown":
            continue
        weight = W_ALARM_TRIGGER * _proximity_scale(at, onset, lead)
        cite = {
            "signal": "alarm",
            "ref": source,
            "at": s(str(at), 40) if at else None,
            "lead_time_s": round((onset - at).total_seconds(), 3) if at else None,
            "detail": s(str(e.get("message", e.get("priority", ""))), 160),
            "_weight": weight,
        }
        key = (source, cause)
        if key not in best or weight > best[key]["cite"]["_weight"]:
            best[key] = {"cause": cause, "cite": cite}
    for entry in best.values():
        weight = entry["cite"].pop("_weight")
        _add(contributions, entry["cause"], weight, entry["cite"])
    return {"count": len(evts), "flood": flood if isinstance(flood, dict) else None}


def _score_tags(tags: list[dict] | None, contributions: dict[str, list[dict]]) -> None:
    """Map tag-health offenders to sensor/process causes by their flags."""
    rows = [t for t in (tags or []) if isinstance(t, dict)]
    if not rows:
        return
    health = tag_health(rows)
    for off in health.get("offenders", []):
        flags = off.get("flags", [])
        severe = off.get("severity", 0) >= 2
        weight = W_TAG_SEVERE if severe else W_TAG_MINOR
        if {"flatline", "bad_quality", "some_bad_quality"} & set(flags):
            cause = "sensor_fault"
        elif {"out_of_range_alarm", "out_of_range_warn", "statistical_anomaly"} & set(flags):
            cause = "mechanical_fault"
        else:
            continue
        _add(contributions, cause, weight, {
            "signal": "tag",
            "ref": s(str(off.get("ref", "")), 96),
            "detail": s(f"flags={','.join(flags)} severity={off.get('severity')}", 160),
        })


def _score_category_prior(category: str | None, contributions: dict[str, list[dict]]) -> None:
    """Seed a weak prior from the stoppage's own category label, if any."""
    if not category:
        return
    cause = _classify_text(category)
    if cause == "unknown":
        return
    _add(contributions, cause, W_DOWNTIME_CATEGORY_PRIOR, {
        "signal": "downtime_category",
        "ref": s(category, 32),
        "detail": "stoppage category prior",
    })


def _classify_text(text: str) -> str:
    """First cause whose keyword appears in ``text`` (case-insensitive), else unknown."""
    low = (text or "").strip().lower()
    if not low:
        return "unknown"
    for cause, keywords in CAUSE_KEYWORDS.items():
        if any(k in low for k in keywords):
            return cause
    return "unknown"


# ─── aggregation / verdict ───────────────────────────────────────────────────


def _noisy_or(weights: list[float]) -> float:
    """Combine independent evidence: 1 - Π(1-wᵢ). Bounded [0,1), rewards agreement."""
    product = 1.0
    for w in weights:
        product *= (1.0 - max(0.0, min(w, 0.999)))
    return 1.0 - product


def _band(confidence: float) -> str:
    if confidence >= HIGH_CONFIDENCE:
        return "high"
    if confidence >= MEDIUM_CONFIDENCE:
        return "medium"
    return "low"


def _build_hypotheses(contributions: dict[str, list[dict]]) -> list[dict]:
    """Aggregate per-cause contributions into ranked, cited hypotheses."""
    hyps: list[dict] = []
    for cause, items in contributions.items():
        confidence = round(_noisy_or([it["weight"] for it in items]), 4)
        if confidence <= 0.0:
            continue
        hyps.append({
            "cause": cause,
            "confidence": confidence,
            "confidence_band": _band(confidence),
            "evidence": sorted(items, key=lambda it: it["weight"], reverse=True),
            "recommended_action": RECOMMENDED_ACTIONS.get(cause, RECOMMENDED_ACTIONS["unknown"]),
        })
    hyps.sort(key=lambda h: (h["confidence"], len(h["evidence"])), reverse=True)
    return hyps


def _decide(hypotheses: list[dict]) -> tuple[str, dict | None]:
    """Pick a verdict + primary cause from the ranked hypotheses."""
    real = [h for h in hypotheses if h["cause"] != "alarm_flood"]
    if not real:
        # Only context (e.g. a flood) and no localizing cause counts as thin.
        return "insufficient_evidence", None
    top = real[0]
    runner = real[1]["confidence"] if len(real) > 1 else 0.0
    if top["confidence"] < MEDIUM_CONFIDENCE:
        return "insufficient_evidence", None
    if top["confidence"] >= HIGH_CONFIDENCE and (top["confidence"] - runner) >= DOMINANCE_MARGIN:
        return "root_cause_identified", top
    return "multiple_candidates", top


def _evidence_summary(
    alarm_ctx: dict, tags: list[dict] | None, dataflow: dict | None,
    contributions: dict[str, list[dict]],
) -> dict:
    """Compact, honest tally of what evidence was actually available + used."""
    flood = (alarm_ctx or {}).get("flood") or {}
    return {
        "alarms_supplied": (alarm_ctx or {}).get("count", 0),
        "alarm_flood_verdict": flood.get("flood_verdict") if flood else None,
        "tags_supplied": len([t for t in (tags or []) if isinstance(t, dict)]),
        "dataflow_verdict": (dataflow or {}).get("verdict") if isinstance(dataflow, dict) else None,
        "causes_with_evidence": sorted(contributions),
        "total_evidence_items": sum(len(v) for v in contributions.values()),
    }


def _next_data(alarm_ctx: dict, tags: list[dict] | None, dataflow: dict | None) -> list[str]:
    """What to collect when the verdict is insufficient — concrete, not generic."""
    wants: list[str] = []
    if not (alarm_ctx or {}).get("count"):
        wants.append("Alarm/condition events ({source, timestamp, message, priority, "
                     "state}) spanning the lead window before onset.")
    if not [t for t in (tags or []) if isinstance(t, dict)]:
        wants.append("Tag samples for the suspect station ({ref, samples:[...], "
                     "warn_high?, alarm_high?}) around the incident.")
    if not isinstance(dataflow, dict) or not dataflow.get("verdict"):
        wants.append("A diagnose_dataflow verdict for the stalled endpoint to "
                     "separate comms loss from field/sensor fault.")
    if not wants:
        wants.append("Widen the lead window or supply a machine-state series so the "
                     "onset can be bounded precisely.")
    return wants


__all__ = ["downtime_rca", "KNOWN_CAUSES", "DEFAULT_CAUSE_WEIGHT",
           "MIN_CAUSE_WEIGHT", "MAX_CAUSE_WEIGHT"]
