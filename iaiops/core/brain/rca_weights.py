"""Learn a per-site RCA cause-weight profile from a labeled incident corpus (PURE).

``rca.downtime_rca`` ships with FIXED per-evidence weights tuned for a generic
plant. Real sites differ: at one plant a ``comms_loss`` alarm almost always *is*
the root cause; at another the same alarm is usually noise downstream of a
mechanical trip. This module derives a per-site ``{cause: multiplier}`` profile
that ``downtime_rca(..., cause_weights=...)`` consumes, so the copilot adapts to
what a site's own confirmed-cause history shows.

The estimator is deliberately **simple and explainable** — no black box:

  weight(c) = clamp( precision(c) / NEUTRAL_PRECISION , MIN , MAX )

where ``precision(c) = P(true cause == c | evidence pointed at c)`` is the
Laplace-smoothed fraction of incidents whose evidence named ``c`` that really
were ``c``. Evidence whose precision beats chance (``NEUTRAL_PRECISION``) is
up-weighted (multiplier > 1); misleading evidence is down-weighted. Two
anti-overfit guards keep a thin/biased corpus from steering the copilot:

  * **smoothing** (Laplace) pulls every estimate toward chance, and
  * a **min-sample guard** — per cause (too few observations ⇒ stay neutral)
    and overall (a corpus below ``MIN_HISTORY`` ⇒ fall back to defaults).

Pure and deterministic: same corpus → same profile, inputs never mutated.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain.rca import (
    CAUSE_KEYWORDS,
    DEFAULT_CAUSE_WEIGHT,
    MAX_CAUSE_WEIGHT,
    MIN_CAUSE_WEIGHT,
)

# Causes a site can *learn* a weight for. ``alarm_flood`` is context, not a
# localizing root cause, so it is intentionally excluded here.
LEARNABLE_CAUSES: frozenset[str] = frozenset(CAUSE_KEYWORDS)

MIN_HISTORY = 8          # below this many incidents ⇒ keep defaults entirely
MIN_CAUSE_SAMPLES = 3    # below this many observations ⇒ keep that cause neutral
NEUTRAL_PRECISION = 0.5  # chance level: precision here ⇒ multiplier 1.0
DEFAULT_SMOOTHING = 1.0  # Laplace pseudo-count pulling toward NEUTRAL_PRECISION


def learn_cause_weights(
    history: Any,
    min_samples: int = MIN_HISTORY,
    smoothing: float = DEFAULT_SMOOTHING,
) -> dict:
    """[PURE] Derive a per-site ``{cause: weight}`` profile from labeled incidents.

    ``history`` is a list of confirmed incidents, each ``{cause, signals}`` where
    ``cause`` is the known/confirmed root cause and ``signals`` are the cause
    labels the evidence pointed at for that incident (both drawn from the copilot's
    cause taxonomy). Returns ``{cause_weights, n_incidents, per_cause, rationale}``:
    ``cause_weights`` is the override map to hand to ``downtime_rca`` (only
    non-neutral, sufficiently-sampled causes appear); ``per_cause`` exposes the
    support/hits/precision behind each weight; ``rationale`` is a short, human
    explanation. Thin history (< ``min_samples``) ⇒ empty map (defaults kept).
    """
    incidents = _validate_history(history)
    n = len(incidents)
    floor = max(1, int(min_samples))
    if n < floor:
        return {
            "cause_weights": {},
            "n_incidents": n,
            "per_cause": {},
            "rationale": (
                f"History too thin ({n} < {floor} confirmed incidents) — keeping "
                "the shipped default cause weights (no per-site adaptation)."
            ),
        }
    support, hits = _tally(incidents)
    smooth = max(0.0, float(smoothing))
    weights, per_cause = _estimate(support, hits, smooth)
    return {
        "cause_weights": weights,
        "n_incidents": n,
        "per_cause": per_cause,
        "rationale": _rationale(weights, per_cause, n),
    }


def _validate_history(history: Any) -> list[dict]:
    """Coerce + validate the corpus at the boundary; teaches on malformed rows."""
    if not isinstance(history, list):
        raise ValueError(
            "history must be a list of {cause, signals} incident records."
        )
    incidents: list[dict] = []
    for i, raw in enumerate(history):
        if not isinstance(raw, dict):
            raise ValueError(f"history[{i}] must be a dict {{cause, signals}}.")
        cause = raw.get("cause")
        if cause not in LEARNABLE_CAUSES:
            raise ValueError(
                f"history[{i}].cause {cause!r} is not a known cause; valid causes: "
                f"{sorted(LEARNABLE_CAUSES)}."
            )
        raw_signals = raw.get("signals", [])
        if not isinstance(raw_signals, (list, tuple)):
            raise ValueError(f"history[{i}].signals must be a list of cause labels.")
        signals = tuple(sig for sig in raw_signals if sig in LEARNABLE_CAUSES)
        incidents.append({"cause": cause, "signals": signals})
    return incidents


def _tally(incidents: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Count, per cause, how often evidence named it (support) and was right (hits)."""
    support: dict[str, int] = {}
    hits: dict[str, int] = {}
    for inc in incidents:
        true_cause = inc["cause"]
        for sig in set(inc["signals"]):  # one incident counts a signal once
            support[sig] = support.get(sig, 0) + 1
            if sig == true_cause:
                hits[sig] = hits.get(sig, 0) + 1
    return support, hits


def _estimate(
    support: dict[str, int], hits: dict[str, int], smoothing: float
) -> tuple[dict[str, float], dict[str, dict]]:
    """Turn tallies into clamped multipliers + a per-cause explanation (sorted)."""
    weights: dict[str, float] = {}
    per_cause: dict[str, dict] = {}
    for cause in sorted(support):
        sup = support[cause]
        hit = hits.get(cause, 0)
        precision = (hit + smoothing) / (sup + 2.0 * smoothing)
        if sup < MIN_CAUSE_SAMPLES:
            mult = DEFAULT_CAUSE_WEIGHT
            note = f"only {sup} observation(s) (< {MIN_CAUSE_SAMPLES}) — left neutral"
        else:
            raw = precision / NEUTRAL_PRECISION
            mult = round(max(MIN_CAUSE_WEIGHT, min(raw, MAX_CAUSE_WEIGHT)), 4)
            note = (f"{hit}/{sup} confirmed when evidence named it "
                    f"(smoothed precision={round(precision, 4)})")
        per_cause[cause] = {
            "support": sup,
            "hits": hit,
            "precision": round(precision, 4),
            "weight": mult,
            "note": note,
        }
        if mult != DEFAULT_CAUSE_WEIGHT:
            weights[cause] = mult
    return weights, per_cause


def _rationale(weights: dict[str, float], per_cause: dict[str, dict], n: int) -> str:
    """One-line, explainable summary of what the profile changed and why."""
    if not weights:
        return (
            f"Learned from {n} incidents: no cause had both enough samples and a "
            "non-chance signal reliability, so the default weights are kept."
        )
    parts = [f"{c}×{w}" for c, w in sorted(weights.items())]
    return (
        f"Learned from {n} incidents (smoothed signal→cause precision, "
        f"{NEUTRAL_PRECISION} = chance). Adjusted: {', '.join(parts)} "
        "(>1 = evidence for this cause is reliable here; <1 = often misleading). "
        f"Causes below {MIN_CAUSE_SAMPLES} samples stay neutral."
    )


__all__ = ["learn_cause_weights", "LEARNABLE_CAUSES", "MIN_HISTORY"]
