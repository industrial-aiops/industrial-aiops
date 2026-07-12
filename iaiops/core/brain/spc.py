"""Statistical process control — Western Electric / Nelson rules (pure).

The fab / quality question: *is this measurement series in statistical control,
or is something special-cause going on?* Given a run of measurements it centers
on the process mean (or a supplied target), estimates sigma (or uses a supplied
one), and applies the standard control-chart rules — a point beyond 3σ, 2-of-3
beyond 2σ, 4-of-5 beyond 1σ, 8-in-a-row one side, 6-point trend — reporting each
violation by index. With spec limits it also reports Cp / Cpk.

Pure function over an injected series; read-only and advisory, every violation
cited by the point index that triggered it.
"""

from __future__ import annotations

from statistics import mean, pstdev

MIN_SAMPLES = 8
MAX_VIOLATIONS = 50


def spc_check(
    series: list,
    target: float | None = None,
    sigma: float | None = None,
    usl: float | None = None,
    lsl: float | None = None,
) -> dict:
    """[READ] Control-chart rule check over a measurement series.

    ``series`` is scalars or ``{value}``. Center is ``target`` if given else the
    series mean; sigma is ``sigma`` if given else the population stdev. Applies
    Western Electric rules 1-4 plus a 6-point Nelson trend, reporting each
    violation by point index. With ``usl`` / ``lsl`` it adds Cp / Cpk. Refuses
    fewer than 8 points.
    """
    values = _values(series)
    if len(values) < MIN_SAMPLES:
        return {"samples": len(values), "verdict": "insufficient_data",
                "needed": MIN_SAMPLES, "note": _NOTE}

    center = float(target) if target is not None else mean(values)
    sd = float(sigma) if sigma is not None else pstdev(values)
    violations = _rule_violations(values, center, sd) if sd > 0 else []

    result = {
        "samples": len(values),
        "center": round(center, 4),
        "sigma": round(sd, 4),
        "verdict": "out_of_control" if violations else "in_control",
        "violation_count": len(violations),
        "violations": violations[:MAX_VIOLATIONS],
        "note": _NOTE,
    }
    if usl is not None and lsl is not None and sd > 0:
        result["capability"] = _capability(center, sd, float(usl), float(lsl))
    return result


_NOTE = (
    "Advisory SPC over an injected series; each violation is cited by the point "
    "index that triggered it. Special-cause signals warrant investigation, not "
    "an automatic reaction — confirm the measurement and the process context."
)


def _values(series: list) -> list[float]:
    out: list[float] = []
    for item in series or []:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(float(value))
    return out


def _rule_violations(values: list[float], center: float, sd: float) -> list[dict]:
    """Apply Western Electric rules 1-4 + a 6-point trend; one entry per hit."""
    zs = [(v - center) / sd for v in values]
    sides = [1 if z > 0 else (-1 if z < 0 else 0) for z in zs]
    hits: list[dict] = []

    for i, z in enumerate(zs):
        if abs(z) > 3:
            hits.append(_hit(1, i, f"point {round(values[i], 4)} beyond 3σ (z={round(z, 2)})"))
    hits += _run_rule(zs, sides, 2.0, 3, 2, rule=2, label="2 of 3 beyond 2σ")
    hits += _run_rule(zs, sides, 1.0, 5, 4, rule=3, label="4 of 5 beyond 1σ")
    hits += _same_side_run(sides, 8, rule=4, label="8 consecutive on one side")
    hits += _trend_run(values, 6, rule=5, label="6-point trend")
    hits.sort(key=lambda h: (h["index"], h["rule"]))
    return hits


def _run_rule(
    zs: list[float], sides: list[int], zmin: float, window: int, need: int,
    rule: int, label: str,
) -> list[dict]:
    """Rule 2/3: ``need`` of ``window`` consecutive points beyond ``zmin``σ, same side."""
    hits: list[dict] = []
    for i in range(len(zs) - window + 1):
        for side in (1, -1):
            count = sum(1 for j in range(i, i + window)
                        if sides[j] == side and abs(zs[j]) > zmin)
            if count >= need:
                hits.append(_hit(rule, i + window - 1, f"{label} (same side)"))
                break
    return hits


def _same_side_run(sides: list[int], run: int, rule: int, label: str) -> list[dict]:
    hits: list[dict] = []
    streak = 0
    prev = 0
    for i, side in enumerate(sides):
        streak = streak + 1 if side != 0 and side == prev else (1 if side != 0 else 0)
        prev = side if side != 0 else prev
        if streak >= run:
            hits.append(_hit(rule, i, label))
    return hits


def _trend_run(values: list[float], run: int, rule: int, label: str) -> list[dict]:
    hits: list[dict] = []
    up = down = 1
    for i in range(1, len(values)):
        up = up + 1 if values[i] > values[i - 1] else 1
        down = down + 1 if values[i] < values[i - 1] else 1
        if up >= run or down >= run:
            hits.append(_hit(rule, i, f"{label} ({'up' if up >= run else 'down'})"))
    return hits


def _capability(center: float, sd: float, usl: float, lsl: float) -> dict:
    cp = (usl - lsl) / (6 * sd)
    cpk = min(usl - center, center - lsl) / (3 * sd)
    return {"cp": round(cp, 3), "cpk": round(cpk, 3), "usl": usl, "lsl": lsl}


def _hit(rule: int, index: int, detail: str) -> dict:
    return {"rule": rule, "index": index, "detail": detail}


__all__ = ["spc_check", "MIN_SAMPLES", "MAX_VIOLATIONS"]
