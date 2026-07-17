"""Energy / carbon analytics — cross-protocol, read-only, pure functions.

The OEE view answers *how well is the asset producing*; this module answers the
adjacent question *how much energy did that production cost, and is it drifting
from where it should be*. Every function is pure over injected series so it is
fully testable without a live plant or a meter:

  * ``energy_intensity`` — energy per produced unit (kWh/piece) + optional carbon
    (kWh × emission factor). The factor is a **caller-configurable** parameter;
    the built-in default is an explicit order-of-magnitude PLACEHOLDER (see
    ``DEFAULT_EMISSION_FACTOR_KG_PER_KWH``) and every carbon result carries the
    assumption so a number is never presented as authoritative.
  * ``energy_baseline_deviation`` — one actual-vs-baseline kWh comparison, with an
    over / under / on-target verdict against a tolerance band.
  * ``energy_baseline_by_period`` — the same comparison across shifts / periods,
    flagging deviation anomalies by two explainable rules: a fixed tolerance band
    **and** a robust (median-absolute-deviation) cross-period outlier test.

No carbon or baseline number is invented: the emission factor is surfaced with
its source, and every deviation is cited by its actual and baseline inputs.
"""

from __future__ import annotations

from statistics import median

from iaiops.core.brain._shared import num, s

MAX_RECORDS = 5000

# Default grid emission factor for OPTIONAL carbon accounting, kg CO2e per kWh.
# This is a PLACEHOLDER, order-of-magnitude value — NOT an authoritative figure.
# Real grid carbon intensity varies widely by region, year and time of day
# (~0 for fully renewable supply to >0.9 for a coal-heavy grid). Always override
# ``emission_factor_kg_per_kwh`` with the site's published factor (grid operator
# / IEA / national inventory) for a defensible number.
# 待核实: no authoritative source is wired in; the default must be replaced.
DEFAULT_EMISSION_FACTOR_KG_PER_KWH = 0.5

# Default tolerance band (fraction) for flagging an actual-vs-baseline deviation.
DEFAULT_ENERGY_TOLERANCE = 0.10

# Iglewicz-Hoaglin modified z-score cutoff for the robust cross-period outlier
# test (|M_i| > k). 3.5 is the value recommended in the original 1993 procedure.
DEFAULT_MAD_K = 3.5

_EMISSION_NOTE = (
    "Carbon = kWh × emission_factor_kg_per_kwh. The default factor "
    f"({DEFAULT_EMISSION_FACTOR_KG_PER_KWH} kg CO2e/kWh) is a PLACEHOLDER "
    "order-of-magnitude value (grid intensity ranges ~0 for renewable supply to "
    ">0.9 for coal-heavy grids); it is NOT authoritative. Pass the site's "
    "published grid factor (operator / IEA / national inventory). 待核实."
)


def _carbon(kwh: float, emission_factor_kg_per_kwh: float | None) -> dict:
    """Carbon block for a kWh quantity; records the factor and its provenance."""
    factor = num(emission_factor_kg_per_kwh)
    if factor is None:
        factor = DEFAULT_EMISSION_FACTOR_KG_PER_KWH
        source = "default_placeholder"
    else:
        factor = max(0.0, factor)
        source = "caller"
    return {
        "co2e_kg": round(kwh * factor, 4),
        "emission_factor_kg_per_kwh": round(factor, 6),
        "factor_source": source,
        "note": _EMISSION_NOTE,
    }


def energy_intensity(
    actual_kwh: float,
    produced_count: float,
    emission_factor_kg_per_kwh: float | None = None,
) -> dict:
    """[READ] Energy per produced unit (kWh/piece) + optional carbon accounting.

    ``kwh_per_unit = actual_kwh / produced_count`` (None when nothing was
    produced). ``carbon`` multiplies kWh by the emission factor; the factor is
    caller-configurable and its default is an explicit placeholder (see
    ``_EMISSION_NOTE``), reported with its source so it is never mistaken for an
    authoritative value.
    """
    kwh = max(0.0, num(actual_kwh) or 0.0)
    count = max(0.0, num(produced_count) or 0.0)
    carbon = _carbon(kwh, emission_factor_kg_per_kwh)
    kwh_per_unit = round(kwh / count, 6) if count > 0 else None
    co2e_kg_per_unit = round(carbon["co2e_kg"] / count, 6) if count > 0 else None
    return {
        "actual_kwh": round(kwh, 4),
        "produced_count": count,
        "kwh_per_unit": kwh_per_unit,
        "carbon": {**carbon, "co2e_kg_per_unit": co2e_kg_per_unit},
    }


def energy_baseline_deviation(
    actual_kwh: float,
    baseline_kwh: float,
    tolerance: float = DEFAULT_ENERGY_TOLERANCE,
) -> dict:
    """[READ] One actual-vs-baseline kWh comparison with an over/under verdict.

    Returns absolute (``deviation_kwh``) and relative (``deviation_pct``)
    deviation. ``status`` is ``over`` / ``under`` / ``on_target`` depending on
    whether ``deviation_pct`` breaks the ± tolerance band. A non-positive
    baseline is reported as ``no_baseline`` (relative deviation is undefined).
    """
    actual = max(0.0, num(actual_kwh) or 0.0)
    base = num(baseline_kwh)
    tol = max(0.0, num(tolerance) if num(tolerance) is not None else DEFAULT_ENERGY_TOLERANCE)
    if base is None or base <= 0:
        return {
            "actual_kwh": round(actual, 4),
            "baseline_kwh": round(max(0.0, base or 0.0), 4),
            "deviation_kwh": None,
            "deviation_pct": None,
            "tolerance_pct": round(tol, 6),
            "status": "no_baseline",
            "exceeds_tolerance": False,
        }
    dev = actual - base
    dev_pct = dev / base
    if dev_pct > tol:
        status = "over"
    elif dev_pct < -tol:
        status = "under"
    else:
        status = "on_target"
    return {
        "actual_kwh": round(actual, 4),
        "baseline_kwh": round(base, 4),
        "deviation_kwh": round(dev, 4),
        "deviation_pct": round(dev_pct, 6),
        "tolerance_pct": round(tol, 6),
        "status": status,
        "exceeds_tolerance": abs(dev_pct) > tol,
    }


def _modified_zscores(values: list[float]) -> list[float]:
    """Iglewicz-Hoaglin modified z-scores — robust, median/MAD based.

    ``M_i = 0.6745·(x_i − median) / MAD``. When MAD is 0 (many identical values)
    fall back to the mean-absolute-deviation form ``(x_i − median)/(1.253314·MeanAD)``
    per the same procedure; when there is no spread at all, every score is 0.
    """
    n = len(values)
    if n == 0:
        return []
    med = median(values)
    abs_dev = [abs(v - med) for v in values]
    mad = median(abs_dev)
    if mad > 0:
        return [round(0.6745 * (v - med) / mad, 4) for v in values]
    mean_ad = sum(abs_dev) / n
    if mean_ad > 0:
        return [round((v - med) / (1.253314 * mean_ad), 4) for v in values]
    return [0.0] * n


def _group_periods(
    records: list[dict], period_key: str, produced_key: str
) -> tuple[list[str], dict]:
    """Sum actual/baseline kWh (and produced count) per period, preserving order."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for r in records:
        period = s(str(r.get(period_key, "")), 48)
        agg = groups.get(period)
        if agg is None:
            agg = {
                "actual_kwh": 0.0,
                "baseline_kwh": 0.0,
                "produced_count": 0.0,
                "has_produced": False,
            }
            groups[period] = agg
            order.append(period)
        agg["actual_kwh"] += max(0.0, num(r.get("actual_kwh")) or 0.0)
        agg["baseline_kwh"] += max(0.0, num(r.get("baseline_kwh")) or 0.0)
        produced = num(r.get(produced_key))
        if produced is not None:
            agg["produced_count"] += max(0.0, produced)
            agg["has_produced"] = True
    return order, groups


def energy_baseline_by_period(
    records: list[dict],
    tolerance: float = DEFAULT_ENERGY_TOLERANCE,
    mad_k: float = DEFAULT_MAD_K,
    emission_factor_kg_per_kwh: float | None = None,
    period_key: str = "period",
    produced_key: str = "produced_count",
) -> dict:
    """[READ] Actual-vs-baseline kWh by shift/period, flagging deviation anomalies.

    Each record: ``{<period_key>, actual_kwh, baseline_kwh, produced_count?}``.
    Records sharing a period are summed. For each period the actual is compared to
    its baseline (abs + pct + tolerance verdict) and, when a produced count is
    given, energy intensity (kWh/unit). A period is flagged as an **anomaly** by
    two independent, explainable rules:

      1. **Tolerance** — ``|deviation_pct|`` exceeds ``tolerance``.
      2. **Robust outlier** — the period's ``deviation_pct`` is more than
         ``mad_k`` Iglewicz-Hoaglin modified z-scores from the cross-period median
         (a spread-based test that does not assume normality).

    Each flagged period reports which rule(s) tripped and the numbers behind them.
    """
    rows = [r for r in (records or [])[:MAX_RECORDS] if isinstance(r, dict)]
    if not rows:
        return {"error": "No records. Pass [{period, actual_kwh, baseline_kwh, produced_count?}]."}

    tol = max(0.0, num(tolerance) if num(tolerance) is not None else DEFAULT_ENERGY_TOLERANCE)
    k = max(0.0, num(mad_k) if num(mad_k) is not None else DEFAULT_MAD_K)
    order, groups = _group_periods(rows, period_key, produced_key)

    # Robust cross-period spread is computed only over periods with a valid
    # (positive-baseline) relative deviation.
    pct_by_period = {
        p: (groups[p]["actual_kwh"] - groups[p]["baseline_kwh"]) / groups[p]["baseline_kwh"]
        for p in order
        if groups[p]["baseline_kwh"] > 0
    }
    mz_periods = list(pct_by_period.keys())
    mz_values = _modified_zscores([pct_by_period[p] for p in mz_periods])
    mz_by_period = dict(zip(mz_periods, mz_values, strict=False))

    periods: list[dict] = []
    total_actual = 0.0
    total_baseline = 0.0
    total_co2 = 0.0
    for period in order:
        agg = groups[period]
        dev = energy_baseline_deviation(agg["actual_kwh"], agg["baseline_kwh"], tol)
        carbon = _carbon(agg["actual_kwh"], emission_factor_kg_per_kwh)
        produced = agg["produced_count"] if agg["has_produced"] else None
        kwh_per_unit = round(agg["actual_kwh"] / produced, 6) if produced and produced > 0 else None
        mz = mz_by_period.get(period)
        robust_outlier = mz is not None and abs(mz) > k
        reasons: list[str] = []
        if dev["exceeds_tolerance"]:
            reasons.append(f"|deviation| {abs(dev['deviation_pct']):.1%} > tolerance {tol:.1%}")
        if robust_outlier:
            reasons.append(f"robust outlier (modified z={mz} beyond ±{k})")
        periods.append(
            {
                "period": period,
                "actual_kwh": dev["actual_kwh"],
                "baseline_kwh": dev["baseline_kwh"],
                "deviation_kwh": dev["deviation_kwh"],
                "deviation_pct": dev["deviation_pct"],
                "status": dev["status"],
                "kwh_per_unit": kwh_per_unit,
                "co2e_kg": carbon["co2e_kg"],
                "exceeds_tolerance": dev["exceeds_tolerance"],
                "modified_zscore": mz,
                "robust_outlier": robust_outlier,
                "anomaly": bool(reasons),
                "reasons": reasons,
            }
        )
        total_actual += agg["actual_kwh"]
        total_baseline += agg["baseline_kwh"]
        total_co2 += carbon["co2e_kg"]

    anomalies = sorted(
        (p for p in periods if p["anomaly"]),
        key=lambda p: abs(p["deviation_pct"]) if p["deviation_pct"] is not None else 0.0,
        reverse=True,
    )
    overall = energy_baseline_deviation(total_actual, total_baseline, tol)
    return {
        "period_count": len(periods),
        "tolerance_pct": round(tol, 6),
        "mad_k": round(k, 4),
        "totals": {
            "actual_kwh": round(total_actual, 4),
            "baseline_kwh": round(total_baseline, 4),
            "deviation_kwh": overall["deviation_kwh"],
            "deviation_pct": overall["deviation_pct"],
            "status": overall["status"],
            "co2e_kg": round(total_co2, 4),
        },
        "emission_factor_kg_per_kwh": _carbon(0.0, emission_factor_kg_per_kwh)[
            "emission_factor_kg_per_kwh"
        ],
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "periods": periods,
        "note": (
            "Anomaly = tolerance-band breach OR robust (Iglewicz-Hoaglin modified "
            "z-score) cross-period outlier; each flagged period cites the rule(s). "
            + _EMISSION_NOTE
        ),
    }


__all__ = [
    "energy_intensity",
    "energy_baseline_deviation",
    "energy_baseline_by_period",
    "DEFAULT_EMISSION_FACTOR_KG_PER_KWH",
    "DEFAULT_ENERGY_TOLERANCE",
    "DEFAULT_MAD_K",
]
