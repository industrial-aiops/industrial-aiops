"""Frozen-threshold PdM reference evaluation, not a plant-performance claim."""

from __future__ import annotations

import hashlib
import math
from statistics import mean

from iaiops.core.brain.pdm import MAX_POINTS, MIN_SAMPLES, pdm_forecast
from iaiops.core.readiness.diagnostic import timestamp
from iaiops.core.readiness.diagnostic_export import json_bytes


def digest(value: object) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def evaluate(data: dict) -> dict:
    """Evaluate independent labelled windows, withholding invalid evidence.

    Labels describe a declared future threshold-crossing event, not a physical
    failure. They never enter the forecast. All split/provenance facts are supplied
    declarations: aliases and fabricated labels cannot be independently verified.
    """
    if not isinstance(data, dict) or data.get("schema") != "iaiops.pdm-dataset/v1":
        raise ValueError("Expected iaiops.pdm-dataset/v1")
    policy = data.get("policy")
    if not isinstance(policy, dict) or not all(
        text(policy.get(k)) for k in ("revision", "unit", "condition")
    ):
        raise ValueError("Declare frozen policy revision, unit and operating condition")
    for key in ("warn_high", "horizon_s", "max_gap_s"):
        if not number(policy.get(key)) or (key != "warn_high" and policy[key] <= 0):
            raise ValueError(f"Invalid policy {key}")
    references, windows = data.get("reference_groups"), data.get("windows")
    if (
        not isinstance(references, list)
        or not isinstance(windows, list)
        or not 1 <= len(windows) <= 100
    ):
        raise ValueError("Supply reference_groups and 1..100 evaluation windows")
    groups, assets = set(), set()
    for group in references:
        if not isinstance(group, dict) or not all(
            text(group.get(k)) for k in ("asset", "source_group")
        ):
            raise ValueError("Reference groups need explicit asset/source_group")
        groups.add(group["source_group"])
        assets.add(group["asset"])
    ids, spans, events, output = set(), {}, set(), []
    counts = {k: 0 for k in ("tp", "fp", "tn", "fn", "abstained")}
    hours, leads, errors = 0.0, [], []
    for window in windows:
        if not isinstance(window, dict) or not all(
            text(window.get(k))
            for k in ("id", "asset", "source_group", "condition", "unit", "declared_by")
        ):
            raise ValueError("Window needs id/asset/source_group/condition/unit/declarant")
        if window["unit"] != policy["unit"] or window["condition"] != policy["condition"]:
            raise ValueError("Window unit/condition does not match frozen policy applicability")
        if window["id"] in ids:
            raise ValueError("Duplicate window id")
        ids.add(window["id"])
        if window["asset"] in assets or window["source_group"] in groups:
            raise ValueError("Reference/evaluation asset or source-group leakage")
        start, end = timestamp(window.get("start")), timestamp(window.get("end"))
        if not 0 < (end - start).total_seconds() <= 86400:
            raise ValueError("Window must span (0, 24h]")
        previous = spans.setdefault(window["asset"], [])
        if any(start < b and a < end for a, b in previous):
            raise ValueError("Overlapping observation windows would double-count exposure")
        previous.append((start, end))
        label = window.get("label")
        if (
            not isinstance(label, dict)
            or not text(label.get("by"))
            or label.get("event") not in (True, False)
            or type(label["event"]) is not bool
        ):
            raise ValueError("Explicit boolean event label and label author required")
        followup = timestamp(label.get("observed_until"))
        if (followup - end).total_seconds() < policy["horizon_s"]:
            raise ValueError("Ground-truth follow-up does not cover the prediction horizon")
        event_at = None
        if label["event"]:
            if not text(label.get("event_id")) or label["event_id"] in events:
                raise ValueError("Each threshold event needs a unique event_id")
            events.add(label["event_id"])
            event_at = timestamp(label.get("event_at"))
            if not 0 < (event_at - end).total_seconds() <= policy["horizon_s"]:
                raise ValueError("Threshold event must follow the observation within the horizon")
        elif label.get("event_at") is not None or label.get("event_id") is not None:
            raise ValueError("Negative labels cannot carry an event")
        samples = window.get("samples")
        if not isinstance(samples, list) or len(samples) > MAX_POINTS:
            raise ValueError("Supply bounded samples; implicit truncation is forbidden")
        gaps, times = [], []
        for sample in samples:
            try:
                if not isinstance(sample, dict):
                    raise ValueError("sample must be an object")
                ts = timestamp(sample.get("ts"))
                if not start <= ts <= end or (times and ts <= times[-1]):
                    raise ValueError("source time outside window, duplicate or out of order")
                times.append(ts)
                if sample.get("quality") != "good" or not number(sample.get("value")):
                    raise ValueError("bad quality or nonfinite value")
            except ValueError as exc:
                if len(gaps) < 8:
                    gaps.append(str(exc))
        if len(samples) < MIN_SAMPLES:
            gaps.append("insufficient samples")
        edges = [start, *times, end]
        if not times or any(
            (b - a).total_seconds() > policy["max_gap_s"] for a, b in zip(edges, edges[1:])
        ):
            gaps.append("missing coverage")
        if samples and not gaps and samples[-1]["value"] >= policy["warn_high"]:
            gaps.append("threshold already crossed; this is not a pre-event prediction")
        forecast = None
        if not gaps:
            forecast = pdm_forecast(
                samples,
                warn_high=policy["warn_high"],
                imminent_within_s=policy["horizon_s"],
                include_waveform=False,
            )
            if forecast.get("unit") != "s" or forecast["status"] == "insufficient_data":
                gaps.append("forecast engine withheld a timed result")
                forecast = None
        alert = None if gaps else forecast["status"] == "imminent"
        if alert is None:
            counts["abstained"] += 1
        else:
            hours += (end - start).total_seconds() / 3600
            counts[
                "tp"
                if alert and label["event"]
                else "fp"
                if alert
                else "fn"
                if label["event"]
                else "tn"
            ] += 1
            if alert and event_at:
                lead = (event_at - end).total_seconds()
                leads.append(lead)
                errors.append(abs(forecast["eta_to_limit"] - lead))
        output.append(
            {
                "id": window["id"],
                "asset": window["asset"],
                "source_group": window["source_group"],
                "unit": window["unit"],
                "condition": window["condition"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "diagnosis_id": digest(
                    {"window": {k: v for k, v in window.items() if k != "label"}, "policy": policy}
                ),
                "status": "insufficient_evidence" if gaps else "scored",
                "gaps": gaps,
                "alert": alert,
                "forecast": forecast,
                "label": label,
            }
        )
    total_hours = sum(
        (timestamp(w["end"]) - timestamp(w["start"])).total_seconds() / 3600 for w in output
    )
    scored = len(windows) - counts["abstained"]
    return {
        "schema": "iaiops.pdm-evaluation/v1",
        "dataset_digest": digest(data),
        "policy": policy,
        "windows": output,
        "metrics": {
            **counts,
            "scored_windows": scored,
            "total_windows": len(windows),
            "coverage": scored / len(windows),
            "labelled_events": len(events),
            "unscored_events": sum(w["alert"] is None and w["label"]["event"] for w in output),
            "event_recall": counts["tp"] / len(events) if events else None,
            "precision": counts["tp"] / (counts["tp"] + counts["fp"])
            if counts["tp"] + counts["fp"]
            else None,
            "scored_observation_hours": hours,
            "total_observation_hours": total_hours,
            "scored_time_coverage": hours / total_hours,
            "false_alarms_per_scored_hour": counts["fp"] / hours if hours else None,
            "mean_matched_lead_s": mean(leads) if leads else None,
            "threshold_eta_mae_s": mean(errors) if errors else None,
            "lifetime_interval_coverage": None,
        },
        "limitations": [
            "Synthetic/operator-labelled threshold events are not physical failures.",
            "Abstentions reduce event recall; scored-only metrics must be read with coverage.",
            "No fitting: reference groups guard declared split; thresholds are frozen.",
            "No automatic training, threshold updates, lifetime calibration or plant validation.",
        ],
    }
