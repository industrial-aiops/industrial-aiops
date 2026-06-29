"""Problem-surfacing / 智能化-lite operations over OPC-UA.

``health_summary`` classifies a list of tag node-ids against warn/alarm
thresholds (from config or supplied inline) and returns ok/warn/alarm counts +
offenders. ``anomaly_scan`` samples one node over a short bounded window and
flags out-of-range readings using simple statistics (mean / stddev) — no ML.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from iaiops.connectors.opcua.ops import (
    MAX_SAMPLE_SECONDS,
    MAX_SAMPLES,
    _coerce_value,
    _read_one,
)
from iaiops.core.brain._shared import num, s
from iaiops.core.runtime.config import MonitorTag
from iaiops.core.runtime.connection import opcua_session


def _resolve_tag(target: Any, ref: str, overrides: dict | None) -> MonitorTag:
    """Resolve thresholds for ``ref`` from inline overrides or config tags."""
    if overrides and ref in overrides:
        o = overrides[ref] or {}
        return MonitorTag(
            ref=ref,
            label=str(o.get("label", "")),
            warn_high=_opt(o.get("warn_high")),
            alarm_high=_opt(o.get("alarm_high")),
            warn_low=_opt(o.get("warn_low")),
            alarm_low=_opt(o.get("alarm_low")),
        )
    configured = target.tag_for(ref)
    return configured or MonitorTag(ref=ref)


def _opt(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def health_summary(
    target: Any,
    node_ids: list[str] | None = None,
    thresholds: dict | None = None,
) -> dict:
    """[READ] Classify tag node-ids against warn/alarm thresholds.

    ``node_ids`` defaults to the endpoint's configured tag refs. ``thresholds``
    optionally overrides per-ref bounds (``{ref: {warn_high, alarm_high, ...}}``).
    Returns ok/warn/alarm/unknown counts plus the offending tags.
    """
    refs = list(node_ids) if node_ids else [t.ref for t in target.tags]
    if not refs:
        return {
            "error": "No tags to evaluate. Pass node_ids or add 'tags' to the "
            "endpoint's config entry.",
        }
    refs = refs[:100]
    results: list[dict] = []
    counts = {"ok": 0, "warn": 0, "alarm": 0, "unknown": 0}
    with opcua_session(target) as client:
        for ref in refs:
            tag = _resolve_tag(target, ref, thresholds)
            desc = _read_one(client, ref)
            value = num(desc.get("value")) if "error" not in desc else None
            if value is None:
                status = "unknown"
            else:
                status = tag.classify(value)
            counts[status] += 1
            results.append(
                {
                    "ref": s(ref, 128),
                    "label": s(tag.label, 64),
                    "value": _coerce_value(desc.get("value")),
                    "status": status,
                }
            )
    offenders = [r for r in results if r["status"] in ("warn", "alarm")]
    overall = "alarm" if counts["alarm"] else "warn" if counts["warn"] else "ok"
    return {
        "endpoint": s(target.name, 64),
        "overall": overall,
        "counts": counts,
        "evaluated": len(results),
        "offenders": offenders,
        "results": results,
    }


def anomaly_scan(
    target: Any,
    node_id: str,
    samples: int = 20,
    interval_ms: int = 200,
    sigma: float = 3.0,
    timeout_s: int = 30,
) -> dict:
    """[READ] Sample a node and flag statistical outliers (mean ± sigma*stddev).

    Bounded: at most ``samples`` (capped) readings or ``timeout_s`` seconds.
    Returns mean/stddev/min/max and any samples outside the band. Pure
    statistics — no ML, no model state.
    """
    samples = max(2, min(int(samples), MAX_SAMPLES))
    interval_ms = max(50, int(interval_ms))
    timeout_s = max(1, min(int(timeout_s), MAX_SAMPLE_SECONDS))
    sigma = max(0.5, float(sigma))
    deadline = time.monotonic() + timeout_s

    values: list[float] = []
    raw: list[dict] = []
    with opcua_session(target) as client:
        node = client.get_node(node_id)
        for _ in range(samples):
            if time.monotonic() >= deadline:
                break
            try:
                dv = node.read_data_value()
                v = num(dv.Value.Value)
                ts = s(dv.SourceTimestamp, 64)
            except Exception as exc:  # noqa: BLE001 — per-sample read error
                raw.append({"error": s(str(exc), 200)})
                v, ts = None, ""
            if v is not None:
                values.append(v)
                raw.append({"value": v, "source_timestamp": ts})
            time.sleep(interval_ms / 1000.0)

    if len(values) < 2:
        return {
            "node_id": s(node_id, 128),
            "samples": len(values),
            "error": "Not enough numeric samples to compute statistics (need >= 2).",
        }

    mean = statistics.fmean(values)
    stddev = statistics.pstdev(values)
    low = mean - sigma * stddev
    high = mean + sigma * stddev
    outliers = [
        {"value": v, "deviation": round(v - mean, 6)}
        for v in values
        if stddev > 0 and (v < low or v > high)
    ]
    return {
        "node_id": s(node_id, 128),
        "samples": len(values),
        "mean": round(mean, 6),
        "stddev": round(stddev, 6),
        "min": min(values),
        "max": max(values),
        "sigma": sigma,
        "band": {"low": round(low, 6), "high": round(high, 6)},
        "outlier_count": len(outliers),
        "outliers": outliers,
    }
