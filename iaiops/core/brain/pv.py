"""PV string performance — underperformer detection (pure).

The solar-plant question: *which strings / inverters are underperforming, and by
how much?* A string that lags its peers (or its irradiance-expected output) is
the signature of soiling, shading, a blown fuse, or a failed module. From
per-string power (and, when available, plane-of-array irradiance + nameplate) it
computes each string's performance ratio against its expected output — or, when
no expected is derivable, against the fleet median — and flags the laggards.

``pv_performance`` is pure over injected readings; read-only and advisory, every
ratio cited by its inputs.
"""

from __future__ import annotations

from statistics import median

MAX_ROWS = 100
STC_IRRADIANCE = 1000.0  # W/m² standard test conditions
DEFAULT_UNDERPERF_PCT = 90.0


def pv_performance(strings: list[dict], underperf_pct: float = DEFAULT_UNDERPERF_PCT) -> dict:
    """[READ] Flag underperforming PV strings vs expected (or fleet-median) output.

    ``strings`` are ``{string, power_w, irradiance_w_m2?, capacity_w?, expected_w?}``.
    A string's expected output is ``expected_w`` if given, else ``capacity_w ×
    irradiance/1000`` when both are present, else the fleet-median power (relative
    mode). Performance ratio = power / expected. Strings below ``underperf_pct``
    (default 90 %) are flagged underperforming; ~zero power is ``offline``.
    Worst-first, each ratio cited by its inputs. Pure, read-only, advisory.
    """
    rows = [r for r in (_row(s) for s in (strings or []) if isinstance(s, dict)) if r]
    if not rows:
        return {"strings_evaluated": 0, "summary": {}, "underperformer_count": 0,
                "underperformers": [], "worst": None, "note": _NOTE}

    fleet_median = median([r["power_w"] for r in rows]) or 0.0
    graded = [_grade(r, fleet_median, underperf_pct) for r in rows]
    summary: dict[str, int] = {}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    flagged = [g for g in graded if g["status"] in ("underperforming", "offline")]
    flagged.sort(key=lambda g: (g["ratioPct"] is not None, g["ratioPct"] if g["ratioPct"] else 0))
    return {
        "strings_evaluated": len(graded),
        "underperf_pct": underperf_pct,
        "fleetMedianPowerW": round(fleet_median, 1),
        "summary": summary,
        "underperformer_count": len(flagged),
        "underperformers": flagged[:MAX_ROWS],
        "worst": flagged[0] if flagged else None,
        "note": _NOTE,
    }


_NOTE = (
    "Advisory PV performance over injected readings; each ratio is cited by its "
    "inputs. An underperforming string points at soiling, shading, a blown fuse "
    "or a failed module — verify at the combiner/string level before dispatching."
)


def _row(source: dict) -> dict | None:
    power = source.get("power_w", source.get("power"))
    if not isinstance(power, (int, float)):
        return None
    return {
        "string": str(source.get("string") or source.get("name") or "?"),
        "power_w": float(power),
        "expected_w": _expected(source),
    }


def _expected(source: dict) -> float | None:
    """Per-string expected power from an explicit value or irradiance × nameplate."""
    explicit = source.get("expected_w")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return float(explicit)
    capacity = source.get("capacity_w")
    irradiance = source.get("irradiance_w_m2")
    have_both = isinstance(capacity, (int, float)) and isinstance(irradiance, (int, float))
    if have_both and irradiance > 0:
        return float(capacity) * float(irradiance) / STC_IRRADIANCE
    return None


def _grade(row: dict, fleet_median: float, underperf_pct: float) -> dict:
    """Ratio vs the string's expected output, else vs the fleet median."""
    expected = row["expected_w"]
    method = "expected"
    if expected is None:
        expected, method = fleet_median, "fleet_median"
    ratio = round(row["power_w"] / expected * 100.0, 1) if expected else None

    if row["power_w"] <= 0:
        status = "offline"
    elif ratio is not None and ratio < underperf_pct:
        status = "underperforming"
    else:
        status = "ok"
    detail = (f"{round(row['power_w'], 1)} W vs {round(expected, 1) if expected else '?'} W "
              f"expected ({method}) — ratio {ratio}%")
    return {"string": row["string"], "power_w": round(row["power_w"], 1),
            "expectedW": round(expected, 1) if expected else None, "method": method,
            "ratioPct": ratio, "status": status, "detail": detail}


__all__ = ["pv_performance", "MAX_ROWS", "DEFAULT_UNDERPERF_PCT"]
