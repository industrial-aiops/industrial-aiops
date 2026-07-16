"""OEE / downtime auto-capture — cross-protocol, read-only analytics.

Protocol-agnostic analysis over **provided / collected** series, so it is fully
testable without a live plant: the caller injects the inputs (planned time, run
state series, counts) and these functions compute the result.

  * ``oee_compute`` — Availability × Performance × Quality from the classic OEE
    inputs (planned time, run time, ideal cycle, total/good counts).
  * ``downtime_events`` — detect running→stopped transitions in a state/tag
    series, produce stoppage events with durations, and categorize them
    (changeover / material / mechanical / quality / break / unknown).
  * ``six_big_losses`` — decompose the OEE gap into the classic Six Big Losses
    (breakdown / setup / minor-stops / speed / startup-rejects / production-rejects)
    as a telescoping time-ladder that always sums back to planned time.
  * ``oee_multidim`` — aggregate OEE across dimensions (machine × part × shift)
    from labelled records, returning the matrix + worst performers.

All outputs are structured JSON designed for an agent to visualize. Each ratio is
reported raw and clamped to [0,1] (a >100% performance, common with a slightly
optimistic ideal cycle, is flagged rather than silently hidden).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from iaiops.core.brain import energy as _energy
from iaiops.core.brain._shared import num, s

MAX_RECORDS = 5000
MAX_SERIES = 10000

# Default state vocabulary: anything in RUNNING_STATES counts as productive run
# time; everything else is a stoppage. Vendor-neutral, case-insensitive.
RUNNING_STATES = frozenset(
    {"RUNNING", "ACTIVE", "AUTO", "PRODUCING", "RUN", "ON", "1", "TRUE", "AVAILABLE"}
)

# Default downtime categories by keyword found in a state/reason label.
DEFAULT_CATEGORY_KEYWORDS = {
    "changeover": ("changeover", "setup", "product change", "tool change"),
    "material": ("material", "starved", "blocked", "no part", "feed"),
    "mechanical": ("fault", "jam", "mechanical", "breakdown", "estop", "e-stop", "trip"),
    "quality": ("quality", "reject", "scrap", "defect"),
    "break": ("break", "lunch", "meeting", "planned", "maintenance"),
}


def _ratio(numerator: float, denominator: float) -> dict:
    """Compute a ratio reporting both the raw value and a [0,1]-clamped value."""
    if denominator <= 0:
        return {"raw": 0.0, "value": 0.0, "capped": False}
    raw = numerator / denominator
    value = max(0.0, min(raw, 1.0))
    return {"raw": round(raw, 6), "value": round(value, 6), "capped": raw > 1.0}


def oee_compute(
    planned_time_s: float,
    run_time_s: float,
    ideal_cycle_time_s: float,
    total_count: float,
    good_count: float,
) -> dict:
    """[READ] OEE = Availability × Performance × Quality from production inputs.

    Availability = run_time / planned_time; Performance = (ideal_cycle ×
    total_count) / run_time; Quality = good_count / total_count. Each factor is
    reported raw + clamped to [0,1]; OEE uses the clamped factors.
    """
    planned = max(0.0, num(planned_time_s) or 0.0)
    run = max(0.0, num(run_time_s) or 0.0)
    ideal = max(0.0, num(ideal_cycle_time_s) or 0.0)
    total = max(0.0, num(total_count) or 0.0)
    good = max(0.0, num(good_count) or 0.0)

    availability = _ratio(run, planned)
    performance = _ratio(ideal * total, run)
    quality = _ratio(good, total)
    oee = round(availability["value"] * performance["value"] * quality["value"], 6)

    losses = {
        "availability_loss_s": round(max(0.0, planned - run), 3),
        "quality_loss_count": round(max(0.0, total - good), 3),
    }
    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
        "oee_pct": round(oee * 100.0, 2),
        "inputs": {
            "planned_time_s": planned,
            "run_time_s": run,
            "ideal_cycle_time_s": ideal,
            "total_count": total,
            "good_count": good,
        },
        "losses": losses,
        "note": "Factors reported raw + clamped to [0,1]; OEE uses clamped factors. "
        "A 'capped' performance >1.0 usually means the ideal cycle time is optimistic.",
    }


# The classic Six Big Losses, grouped under the OEE factor each one erodes. The
# third element marks the *residual* bucket of its factor — the one that absorbs
# whatever measured loss the named split does not explain (breakdown = unplanned
# downtime, speed loss, production rejects).
SIX_BIG_LOSSES = (
    ("breakdown", "availability", True),
    ("setup", "availability", False),
    ("minor_stops", "performance", False),
    ("speed_loss", "performance", True),
    ("startup_rejects", "quality", False),
    ("production_rejects", "quality", True),
)


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into ``[lo, hi]`` (``hi`` is honoured over ``lo``)."""
    return max(lo, min(value, hi))


def _split_availability(
    avail_loss: float, breakdown: float | None, setup: float | None
) -> tuple[float, float, float, bool]:
    """Split availability loss into setup (named) + breakdown (residual/unplanned).

    Setup is the planned-changeover portion when supplied; breakdown absorbs the
    remaining unplanned downtime, so the whole availability loss is attributed even
    with no split. If breakdown is *also* supplied it is honoured and any leftover
    becomes ``unclassified``. Supplied values are clamped to the measured loss
    (authoritative); ``over`` flags an input that exceeded it.
    """
    su = _clamp(setup, 0.0, avail_loss) if setup is not None else 0.0
    over = setup is not None and setup > avail_loss
    remaining = avail_loss - su
    if breakdown is not None:
        bd = _clamp(breakdown, 0.0, remaining)
        over = over or breakdown > remaining
        unclassified = remaining - bd
    else:
        bd = remaining  # residual: unplanned downtime not attributed to setup
        unclassified = 0.0
    return bd, su, unclassified, over


def _loss_entry(
    loss: str, bucket: str, time_s: float, planned: float, classified: bool, count: float | None
) -> dict:
    """One Six-Big-Losses row: its time, the OEE points it costs, provenance."""
    entry = {
        "loss": loss,
        "bucket": bucket,
        "time_s": round(time_s, 3),
        # Every loss's share of planned time is exactly the OEE points it costs:
        # the shares sum with OEE to 1.0 (see the identity in the return note).
        "pct_of_planned": round(time_s / planned, 6) if planned > 0 else 0.0,
        "classified": classified,
    }
    if count is not None:
        entry["count"] = round(count, 3)
    return entry


def six_big_losses(
    planned_time_s: float,
    run_time_s: float,
    ideal_cycle_time_s: float,
    total_count: float,
    good_count: float,
    breakdown_time_s: float | None = None,
    setup_time_s: float | None = None,
    minor_stop_time_s: float | None = None,
    startup_reject_count: float | None = None,
) -> dict:
    """[READ] Decompose the OEE gap into the Six Big Losses (time-ladder).

    Attributes every second of planned time to either fully-productive output or
    one of the six losses, using the telescoping ladder that underlies OEE:

        Planned = FullyProductive
                + Availability(breakdown + setup)
                + Performance(minor stops + speed)
                + Quality(startup + production rejects)

    where FullyProductive = ideal_cycle × good_count. Each stage is min-clamped so
    the ladder always sums exactly back to planned time and ``oee_from_losses`` =
    FullyProductive / Planned equals the classic OEE (they only diverge when the
    ideal cycle is *optimistic* — net run time exceeds run time — which is flagged
    as ``optimistic_cycle``).

    Optional split inputs refine the residual buckets: ``breakdown_time_s`` /
    ``setup_time_s`` split availability (leftover → ``unclassified``);
    ``minor_stop_time_s`` splits performance (leftover → speed loss);
    ``startup_reject_count`` splits quality (leftover → production rejects). A
    split that exceeds its measured bucket is scaled down and noted, since the
    measured bucket total is authoritative. Each loss row is marked ``classified``
    when a real split input shaped it. ``pct_of_planned`` is the OEE points that
    loss costs; the six shares sum with OEE to 1.0.
    """
    planned = max(0.0, num(planned_time_s) or 0.0)
    ideal = max(0.0, num(ideal_cycle_time_s) or 0.0)
    total = max(0.0, num(total_count) or 0.0)
    good = _clamp(num(good_count) or 0.0, 0.0, total)
    run = _clamp(num(run_time_s) or 0.0, 0.0, planned)

    avail_loss = planned - run
    nrt = ideal * total
    nrt_eff = _clamp(nrt, 0.0, run)
    perf_loss = run - nrt_eff
    fpt = _clamp(ideal * good, 0.0, nrt_eff)
    qual_loss = nrt_eff - fpt

    warnings: list[str] = []
    # Availability split: setup (named) + breakdown (residual/unplanned downtime).
    bd, su, other_avail, avail_over = _split_availability(
        avail_loss, breakdown_time_s, setup_time_s
    )
    if avail_over:
        warnings.append("breakdown/setup exceeded measured availability loss — clamped to fit")

    # Performance split: minor stops (given) vs speed loss (residual).
    minor = minor_stop_time_s
    if minor is not None:
        minor = _clamp(minor, 0.0, perf_loss)
        if (minor_stop_time_s or 0.0) > perf_loss:
            warnings.append("minor_stop_time_s exceeded measured performance loss — capped")
    minor_val = minor if minor is not None else 0.0
    speed = perf_loss - minor_val
    perf_classified = minor_stop_time_s is not None

    # Quality split: startup rejects (given, count) vs production rejects (residual).
    reject_count = max(0.0, total - good)
    startup_ct = startup_reject_count
    if startup_ct is not None:
        clamped_ct = _clamp(startup_ct, 0.0, reject_count)
        if startup_ct > reject_count:
            warnings.append("startup_reject_count exceeded total rejects — capped")
        startup_ct = clamped_ct
    startup_ct_val = startup_ct if startup_ct is not None else 0.0
    startup_time = _clamp(ideal * startup_ct_val, 0.0, qual_loss)
    production_time = qual_loss - startup_time
    production_ct = max(0.0, reject_count - startup_ct_val)
    qual_classified = startup_reject_count is not None

    # ``classified`` marks a row shaped by a real split input (breakdown defaults
    # to the residual/unplanned bucket, so it is classified only when supplied).
    values = {
        "breakdown": (bd, breakdown_time_s is not None, None),
        "setup": (su, setup_time_s is not None, None),
        "minor_stops": (minor_val, perf_classified, None),
        "speed_loss": (speed, perf_classified, None),
        "startup_rejects": (startup_time, qual_classified, startup_ct_val),
        "production_rejects": (production_time, qual_classified, production_ct),
    }
    losses = [
        _loss_entry(name, bucket, values[name][0], planned, values[name][1], values[name][2])
        for name, bucket, _residual in SIX_BIG_LOSSES
    ]
    ranked = sorted(losses, key=lambda e: e["time_s"], reverse=True)

    ladder_sum = fpt + qual_loss + perf_loss + avail_loss
    return {
        "planned_time_s": round(planned, 3),
        "fully_productive_time_s": round(fpt, 3),
        "oee_from_losses": round(fpt / planned, 6) if planned > 0 else 0.0,
        "by_bucket": {
            "availability": {
                "loss_s": round(avail_loss, 3),
                "pct_of_planned": round(avail_loss / planned, 6) if planned > 0 else 0.0,
            },
            "performance": {
                "loss_s": round(perf_loss, 3),
                "pct_of_planned": round(perf_loss / planned, 6) if planned > 0 else 0.0,
            },
            "quality": {
                "loss_s": round(qual_loss, 3),
                "pct_of_planned": round(qual_loss / planned, 6) if planned > 0 else 0.0,
            },
        },
        "losses": losses,
        "largest_loss": ranked[0] if ranked else None,
        "ranked": ranked,
        "unclassified": {"availability_s": round(other_avail, 3)},
        "optimistic_cycle": nrt > run,
        "fully_classified": (
            (breakdown_time_s is not None or setup_time_s is not None)
            and perf_classified
            and qual_classified
        ),
        "input_warnings": warnings,
        "identity_ok": abs(ladder_sum - planned) < 1e-6,
        "note": (
            "Six Big Losses time-ladder: Planned = FullyProductive + Availability "
            "(setup+breakdown) + Performance (minor stops+speed) + Quality (startup+"
            "production rejects). Each loss's pct_of_planned is the OEE points it "
            "costs; the six shares sum with OEE to 1.0. Breakdown, speed loss and "
            "production rejects are residual buckets (measured loss minus the named "
            "split). When optimistic_cycle is true (net run > run time) "
            "oee_from_losses may diverge from the multiplicative OEE — cycle too fast."
        ),
    }


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerant of a trailing Z), else None.

    Naive timestamps are coerced to UTC so a series mixing naive and aware (``Z``)
    stamps can be sorted/subtracted without an offset-naive/aware TypeError.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _is_running(state: Any) -> bool:
    """True if a state/value counts as productive run time."""
    if isinstance(state, bool):
        return state
    if isinstance(state, (int, float)):
        return state != 0
    return str(state).strip().upper() in RUNNING_STATES


def _categorize(label: str, category_map: dict[str, str] | None) -> str:
    """Map a stoppage state/reason label to a downtime category."""
    text = (label or "").strip().lower()
    if category_map:
        # Exact (case-insensitive) state→category override wins.
        for key, cat in category_map.items():
            if key.strip().lower() == text:
                return s(str(cat), 32)
    for cat, keywords in DEFAULT_CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return "unknown"


def downtime_events(
    series: list[dict],
    category_map: dict[str, str] | None = None,
    min_duration_s: float = 0.0,
) -> dict:
    """[READ] Detect running→stopped transitions and categorize the stoppages.

    Each sample: ``{timestamp, state}`` (or ``value``); ``state`` may be a string
    (RUNNING/IDLE/FAULT…), a bool, or a number. The series is sorted by timestamp;
    every span where the machine is NOT running becomes a stoppage event with a
    duration and a category (changeover/material/mechanical/quality/break/unknown).
    """
    rows: list[dict] = []
    for item in (series or [])[:MAX_SERIES]:
        if not isinstance(item, dict):
            continue
        ts = _parse_ts(item.get("timestamp") or item.get("time"))
        if ts is None:
            continue
        state = item.get("state", item.get("value"))
        rows.append({"ts": ts, "state": state})
    rows.sort(key=lambda r: r["ts"])
    if len(rows) < 2:
        return {
            "error": "Need >=2 timestamped samples to detect transitions.",
            "samples": len(rows),
        }

    events: list[dict] = []
    open_event: dict | None = None
    for i, row in enumerate(rows):
        running = _is_running(row["state"])
        if not running and open_event is None:
            open_event = {"start_ts": row["ts"], "state": row["state"]}
        elif running and open_event is not None:
            _close_event(events, open_event, row["ts"], category_map)
            open_event = None
    if open_event is not None:
        _close_event(events, open_event, rows[-1]["ts"], category_map)

    events = [e for e in events if e["duration_s"] >= max(0.0, min_duration_s)]
    by_category: dict[str, dict] = {}
    for e in events:
        agg = by_category.setdefault(e["category"], {"count": 0, "downtime_s": 0.0})
        agg["count"] += 1
        agg["downtime_s"] = round(agg["downtime_s"] + e["duration_s"], 3)
    total_downtime = round(sum(e["duration_s"] for e in events), 3)
    return {
        "samples": len(rows),
        "event_count": len(events),
        "total_downtime_s": total_downtime,
        "by_category": by_category,
        "events": events[:MAX_RECORDS],
    }


def _close_event(
    events: list[dict], open_event: dict, end_ts: datetime, category_map: dict | None
) -> None:
    """Finalize a stoppage span into an event record."""
    duration = max(0.0, (end_ts - open_event["start_ts"]).total_seconds())
    label = str(open_event["state"]) if open_event["state"] is not None else ""
    events.append(
        {
            "start": s(str(open_event["start_ts"]), 40),
            "end": s(str(end_ts), 40),
            "duration_s": round(duration, 3),
            "state": s(label, 48),
            "category": _categorize(label, category_map),
        }
    )


def oee_multidim(
    records: list[dict],
    dimensions: list[str] | None = None,
    emission_factor_kg_per_kwh: float | None = None,
    energy_tolerance: float = _energy.DEFAULT_ENERGY_TOLERANCE,
) -> dict:
    """[READ] Aggregate OEE (and optional energy) across dimensions.

    Each record carries dimension labels plus the OEE inputs (``planned_time_s``,
    ``run_time_s``, ``ideal_cycle_time_s``, ``total_count``, ``good_count``) and,
    optionally, ``actual_kwh`` / ``baseline_kwh``. Records sharing the same
    dimension-tuple are summed, then OEE is computed for the group. Returns the
    matrix + the worst performers (lowest OEE).

    When any record carries energy, each matrix row gains an ``energy`` block
    (kWh/unit, actual-vs-baseline deviation, carbon) and a top-level
    ``energy_baseline`` block flags cross-group deviation anomalies — grouping by
    ``dimensions=["shift"]`` yields the classic by-shift energy comparison.
    """
    dims = [str(d) for d in (dimensions or ["machine", "part", "shift"])][:6]
    rows = [r for r in (records or [])[:MAX_RECORDS] if isinstance(r, dict)]
    if not rows:
        return {"error": "No records. Pass [{<dimensions>, planned_time_s, ...}]."}

    groups: dict[tuple, dict] = {}
    for r in rows:
        key = tuple(s(str(r.get(d, "")), 48) for d in dims)
        agg = groups.setdefault(
            key,
            {
                "planned_time_s": 0.0,
                "run_time_s": 0.0,
                "ideal_cycle_time_s": 0.0,
                "total_count": 0.0,
                "good_count": 0.0,
                "actual_kwh": 0.0,
                "baseline_kwh": 0.0,
                "_ideal_n": 0,
                "_has_energy": False,
            },
        )
        agg["planned_time_s"] += num(r.get("planned_time_s")) or 0.0
        agg["run_time_s"] += num(r.get("run_time_s")) or 0.0
        agg["total_count"] += num(r.get("total_count")) or 0.0
        agg["good_count"] += num(r.get("good_count")) or 0.0
        ideal = num(r.get("ideal_cycle_time_s"))
        if ideal is not None:
            agg["ideal_cycle_time_s"] += ideal
            agg["_ideal_n"] += 1
        actual_kwh = num(r.get("actual_kwh"))
        baseline_kwh = num(r.get("baseline_kwh"))
        if actual_kwh is not None or baseline_kwh is not None:
            agg["actual_kwh"] += max(0.0, actual_kwh or 0.0)
            agg["baseline_kwh"] += max(0.0, baseline_kwh or 0.0)
            agg["_has_energy"] = True

    matrix: list[dict] = []
    energy_records: list[dict] = []
    for key, agg in groups.items():
        ideal_avg = agg["ideal_cycle_time_s"] / agg["_ideal_n"] if agg["_ideal_n"] else 0.0
        oee = oee_compute(
            agg["planned_time_s"],
            agg["run_time_s"],
            ideal_avg,
            agg["total_count"],
            agg["good_count"],
        )
        dim_labels = dict(zip(dims, key, strict=False))
        row = {
            "dimensions": dim_labels,
            "oee": oee["oee"],
            "oee_pct": oee["oee_pct"],
            "availability": oee["availability"]["value"],
            "performance": oee["performance"]["value"],
            "quality": oee["quality"]["value"],
        }
        if agg["_has_energy"]:
            row["energy"] = _group_energy(agg, emission_factor_kg_per_kwh, energy_tolerance)
            energy_records.append(
                {
                    "period": " × ".join(key) or "(all)",
                    "actual_kwh": agg["actual_kwh"],
                    "baseline_kwh": agg["baseline_kwh"],
                    "produced_count": agg["good_count"],
                }
            )
        matrix.append(row)
    matrix.sort(key=lambda m: m["oee"])
    overall = round(sum(m["oee"] for m in matrix) / len(matrix), 6) if matrix else 0.0
    result = {
        "dimensions": dims,
        "group_count": len(matrix),
        "mean_oee": overall,
        "worst_performers": matrix[: min(5, len(matrix))],
        "matrix": matrix,
    }
    if energy_records:
        result["energy_baseline"] = _energy.energy_baseline_by_period(
            energy_records,
            tolerance=energy_tolerance,
            emission_factor_kg_per_kwh=emission_factor_kg_per_kwh,
        )
    return result


def _group_energy(agg: dict, emission_factor_kg_per_kwh: float | None, tolerance: float) -> dict:
    """Per-group energy rollup: intensity (kWh/good unit) + baseline deviation."""
    intensity = _energy.energy_intensity(
        agg["actual_kwh"], agg["good_count"], emission_factor_kg_per_kwh
    )
    deviation = _energy.energy_baseline_deviation(agg["actual_kwh"], agg["baseline_kwh"], tolerance)
    return {
        "actual_kwh": intensity["actual_kwh"],
        "baseline_kwh": deviation["baseline_kwh"],
        "kwh_per_unit": intensity["kwh_per_unit"],
        "deviation_pct": deviation["deviation_pct"],
        "status": deviation["status"],
        "exceeds_tolerance": deviation["exceeds_tolerance"],
        "co2e_kg": intensity["carbon"]["co2e_kg"],
    }


__all__ = ["oee_compute", "six_big_losses", "downtime_events", "oee_multidim"]
