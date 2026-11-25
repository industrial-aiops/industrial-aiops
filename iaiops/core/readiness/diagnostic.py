"""Single-window, read-only conveyor observation readiness. No device/model I/O.

A supplied point map is an operator declaration, not discovered semantics. This
reference capability detects stops; it never infers their physical cause.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from iaiops.core.brain.oee_measure import MIN_SAMPLES, measure_availability
from iaiops.core.runtime.config import MonitorTag, TagRole


def timestamp(value: Any) -> datetime:
    """Require an explicit timezone; silently guessing UTC hides clock errors."""
    if not isinstance(value, str):
        raise ValueError("Timestamp must be an ISO-8601 string with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Timestamp must be ISO-8601 with timezone") from exc
    if result.tzinfo is None:
        raise ValueError("Timestamp needs an explicit timezone")
    return result.astimezone(UTC)


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def assess_diagnostic(data: dict, *, now: datetime, replay: bool = False) -> dict:
    """Assess this input/window only; a replay can never assert live readiness.

    This first reference contract deliberately requires continuous, good-quality,
    chronological samples with explicit endpoint/ref and a closed state vocabulary.
    A new adapter must preserve these facts, not substitute receipt time for source time.
    """
    if not isinstance(data, dict) or data.get("schema") != "iaiops.conveyor-observation/v1":
        raise ValueError("Expected iaiops.conveyor-observation/v1 input")
    for key in ("window", "policy", "mapping"):
        if not isinstance(data.get(key), dict):
            raise ValueError(f"{key} must be an object")
    start, end = (timestamp(data.get("window", {}).get(k)) for k in ("start", "end"))
    if end <= start or (end - start).total_seconds() > 86400:
        raise ValueError("Observation window must be positive and at most 24 hours")
    if now.tzinfo is None:
        raise ValueError("Assessment time needs an explicit timezone")
    now = now.astimezone(UTC)
    policy = data.get("policy", {})
    gap, age = policy.get("max_gap_s"), policy.get("max_age_s")
    if not all(_number(v) and 0 < v <= 3600 for v in (gap, age)):
        raise ValueError("Declare max_gap_s/max_age_s in (0, 3600]")
    mapping = data.get("mapping") or {}
    config_gaps = []
    required = ("endpoint", "ref", "declared_by")
    if not all(isinstance(mapping.get(k), str) and mapping[k].strip() for k in required):
        config_gaps.append("Supply endpoint, ref and the person declaring the point semantics.")
    states, running = mapping.get("known_values"), mapping.get("running_when")
    if (
        not isinstance(states, list)
        or not states
        or not all(_number(v) for v in states)
        or not isinstance(running, list)
        or not running
        or not all(_number(v) and v in states for v in running)
    ):
        config_gaps.append("Declare numeric known_values and a nonempty running_when subset.")
    samples = data.get("samples")
    if not isinstance(samples, list) or len(samples) > 100_000:
        raise ValueError("samples must be a list of at most 100000 rows")
    gaps = []
    rows = []
    last = None
    for index, row in enumerate(samples):
        try:
            if not isinstance(row, dict):
                raise ValueError("row is not an object")
            ts = timestamp(row.get("ts"))
            if not start <= ts <= end:
                raise ValueError("source timestamp is outside the observation window")
            if last is not None and ts <= last:
                raise ValueError("source timestamps are duplicate or out of order")
            last = ts
            if row.get("endpoint") != mapping.get("endpoint") or row.get("ref") != mapping.get(
                "ref"
            ):
                raise ValueError("endpoint/ref does not match the declared point")
            if row.get("quality") != "good" or row.get("historical") is not False:
                raise ValueError("requires good quality and explicitly non-historical samples")
            value = row.get("value")
            if not _number(value) or not isinstance(states, list) or value not in states:
                raise ValueError("value is invalid or outside the declared state vocabulary")
            rows.append(row)
        except ValueError as exc:
            # Bounded teaching error, never echo arbitrary input into an agent result.
            if len(gaps) < 10:
                gaps.append(f"Sample {index}: {exc}; repair/recollect the source evidence.")
    if len(rows) < MIN_SAMPLES:
        gaps.append(f"Collect at least {MIN_SAMPLES} valid samples in the window.")
    times = [timestamp(r["ts"]) for r in rows]
    if times:
        edges = [start, *times, end]
        if any((b - a).total_seconds() > gap for a, b in zip(edges, edges[1:])):
            gaps.append("Observation has a coverage gap; recollect within max_gap_s.")
    assessed_at = end if replay else now
    if end > now or (times and max(times) > now):
        gaps.append("Source/window time is in the future; verify clock synchronization.")
    if not replay and (now - end).total_seconds() > age:
        gaps.append("Observation window is stale; collect a current window.")
    if times and (assessed_at - times[-1]).total_seconds() > age:
        gaps.append("Last source sample is stale; receipt time cannot renew its validity.")
    diagnostic = None
    if not config_gaps and not gaps:
        tag = MonitorTag(ref=mapping["ref"], role=TagRole.RUN_STATE, running_when=tuple(running))
        measured = measure_availability(rows, tag, window=(start.isoformat(), end.isoformat()))
        if measured["status"] != "ok" or measured.get("unknown_s", 0) > 0:
            gaps.append(
                "Measurement engine withheld a complete observation; inspect source coverage."
            )
        else:
            diagnostic = {
                "kind": "observed_stop_windows",
                "measurement": measured,
                "root_cause": None,
                "note": "Run-state evidence detects stops/duration only; cause is unverified.",
            }
    ready = not config_gaps and not gaps
    return {
        "schema": "iaiops.diagnostic-card/v1",
        "capability": "conveyor_stop_observation",
        "mode": "historical_replay" if replay else "current_window",
        "configuration": {"status": "blocked" if config_gaps else "ready", "gaps": config_gaps},
        "evidence": {"status": "sufficient" if ready else "insufficient", "gaps": gaps},
        "status": "ready"
        if ready
        else "insufficient_evidence"
        if not config_gaps
        else "unconfigured",
        "live_readiness": ready and not replay,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": now.isoformat(),
        "valid_until": None if replay else (end + timedelta(seconds=age)).isoformat(),
        "assessed_at": assessed_at.isoformat(),
        "valid_samples": len(rows),
        "diagnostic": diagnostic,
        "limitations": [
            "Declarations and provenance are operator-supplied, not independently attested.",
            "No device contact/write, physical cause, production validation or certification.",
            "Replay sufficiency does not establish current operational readiness.",
        ],
    }
