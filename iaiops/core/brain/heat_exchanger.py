"""Heat-exchanger fouling — effectiveness trend from temperatures (pure).

The process-industry maintenance question: *is this exchanger fouling?* As a
shell-and-tube or plate exchanger fouls, its thermal effectiveness falls and the
approach temperature (hot-outlet minus cold-inlet) rises — visible in the four
stream temperatures long before it forces a shutdown. From a series of readings
it computes the hot-side temperature effectiveness ε = (T_hot_in − T_hot_out) /
(T_hot_in − T_cold_in), tracks whether it is declining, and flags fouling.

``heat_exchanger_fouling`` is pure over injected temperature readings; read-only
and advisory, the verdict cited by the effectiveness numbers behind it.
"""

from __future__ import annotations

MIN_SAMPLES = 6

# Fouling defaults: effectiveness below this is poor; a decline of this many %
# from the first half of the window to the second half signals fouling.
DEFAULT_MIN_EFFECTIVENESS = 0.5
DEFAULT_DECLINE_PCT = 10.0


def heat_exchanger_fouling(
    readings: list[dict],
    min_effectiveness: float = DEFAULT_MIN_EFFECTIVENESS,
    decline_pct: float = DEFAULT_DECLINE_PCT,
) -> dict:
    """[READ] Detect heat-exchanger fouling from a series of stream temperatures.

    ``readings`` are ``{hot_in, hot_out, cold_in, cold_out?}`` (°C, in time order).
    Hot-side effectiveness ε = (hot_in − hot_out)/(hot_in − cold_in) is computed
    per reading; the window's first-half vs second-half mean gives the decline.
    Verdict is ``fouling`` when the mean is below ``min_effectiveness`` or the
    decline exceeds ``decline_pct``, else ``ok``. Refuses fewer than 6 readings.
    Every number is cited.
    """
    eff = [
        e
        for e in (_effectiveness(r) for r in (readings or []) if isinstance(r, dict))
        if e is not None
    ]
    if len(eff) < MIN_SAMPLES:
        return {
            "readings": len(eff),
            "verdict": "insufficient_data",
            "needed": MIN_SAMPLES,
            "note": _NOTE,
        }

    half = len(eff) // 2
    first_mean = sum(eff[:half]) / half
    second_mean = sum(eff[half:]) / (len(eff) - half)
    decline = round((first_mean - second_mean) / first_mean * 100.0, 1) if first_mean else 0.0
    mean_eff = sum(eff) / len(eff)

    verdict, detail = _verdict(mean_eff, eff[-1], decline, min_effectiveness, decline_pct)
    return {
        "readings": len(eff),
        "currentEffectiveness": round(eff[-1], 3),
        "meanEffectiveness": round(mean_eff, 3),
        "declinePct": decline,
        "verdict": verdict,
        "detail": detail,
        "note": _NOTE,
    }


_NOTE = (
    "Advisory fouling read over injected stream temperatures; the verdict is "
    "cited by the effectiveness numbers. Falling effectiveness / rising approach "
    "temperature is the fouling signature — schedule a clean, not an automatic trip."
)


def _effectiveness(reading: dict) -> float | None:
    """Hot-side temperature effectiveness for one reading; None if not computable."""
    hot_in = reading.get("hot_in")
    hot_out = reading.get("hot_out")
    cold_in = reading.get("cold_in")
    if not all(isinstance(v, (int, float)) for v in (hot_in, hot_out, cold_in)):
        return None
    denom = hot_in - cold_in
    if denom <= 0:
        return None  # no driving temperature difference — cannot judge
    return (hot_in - hot_out) / denom


def _verdict(
    mean_eff: float,
    current: float,
    decline: float,
    min_eff: float,
    decline_pct: float,
) -> tuple[str, str]:
    if mean_eff < min_eff:
        return "fouling", f"mean effectiveness {round(mean_eff, 3)} below {min_eff}"
    if decline > decline_pct:
        return "fouling", f"effectiveness declined {decline}% across the window (> {decline_pct}%)"
    return "ok", f"effectiveness {round(current, 3)} stable and above {min_eff}"


__all__ = ["heat_exchanger_fouling", "MIN_SAMPLES"]
