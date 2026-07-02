"""Live evidence collection for the downtime root-cause copilot (READ-ONLY).

``rca.downtime_rca`` is pure — it analyzes *injected* evidence. This module is the
thin **live layer** that gathers that evidence from a real endpoint so an operator
can ask "why did line1 stop at 10:00?" without hand-assembling the bundle. It
reuses the existing read paths only:

  * ``diagnose_dataflow`` — the cross-protocol connect→read→freshness→variance probe.
  * ``monitor._read_point`` — one bounded read per ref, sampled ``sample_count``
    times into a series so ``tag_health`` can see flatline / bad-quality / anomaly.
  * OPC-UA ``read_alarms`` — best-effort active-condition surfacing (OPC-UA only;
    other protocols contribute no alarms here).

Like ``analysis.health_summary`` and ``asset_inventory`` this connects to live
gear, so it is exercised with monkeypatched readers rather than a live plant. It
adds light read load and is non-destructive; every probe degrades to an empty /
error-tagged result rather than raising, so a partial outage still yields a
usable evidence bundle for the copilot.
"""

from __future__ import annotations

import time
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.brain.diagnostics import diagnose_dataflow
from iaiops.core.brain.monitor import MIN_INTERVAL_MS, _read_point
from iaiops.core.brain.rca import downtime_rca
from iaiops.core.brain.rca_history import gather_pre_incident

MAX_REFS = 20
MAX_SAMPLES_PER_REF = 60
DEFAULT_SAMPLE_COUNT = 8
DEFAULT_INTERVAL_MS = 200


def collect_evidence(
    target: Any,
    refs: list[str] | None = None,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    include_alarms: bool = True,
    freshness_threshold_s: int = 60,
) -> dict:
    """[READ] Gather a copilot evidence bundle from a live endpoint.

    Returns ``{dataflow, tags, alarms, collected}`` shaped exactly as
    ``downtime_rca`` consumes — ``dataflow`` is a diagnose_dataflow verdict,
    ``tags`` are per-ref sampled series (with config thresholds when known), and
    ``alarms`` are active conditions (OPC-UA only). ``collected`` is an honest
    tally of what was actually obtained.
    """
    ref_list = [r for r in (refs or []) if r][:MAX_REFS]
    primary = ref_list[0] if ref_list else None
    dataflow = diagnose_dataflow(target, primary, freshness_threshold_s)
    tags = [_sample_tag(target, ref, sample_count, interval_ms) for ref in ref_list]
    alarms = _collect_alarms(target) if include_alarms else []
    return {
        "dataflow": dataflow,
        "tags": tags,
        "alarms": alarms,
        "collected": {
            "endpoint": s(getattr(target, "name", ""), 64),
            "protocol": s(getattr(target, "protocol", ""), 16),
            "refs_sampled": len(tags),
            "alarms_found": len(alarms),
            "dataflow_verdict": dataflow.get("verdict") if isinstance(dataflow, dict) else None,
        },
    }


def downtime_rca_live(
    target: Any,
    window: dict[str, Any],
    refs: list[str] | None = None,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    include_alarms: bool = True,
    lead_window_s: float = 300.0,
) -> dict:
    """[READ] Collect live evidence for an endpoint, then run the RCA copilot.

    Convenience over ``collect_evidence`` + ``downtime_rca``: same advisory,
    read-only, evidence-cited contract — the only difference is the evidence is
    pulled from the device instead of injected. The gathered bundle is echoed
    back under ``collected_evidence`` for transparency (no hidden inputs).

    When a per-site ``historian:`` block is configured (A7), the pre-incident
    window is additionally pulled from that reader and scored as historian
    evidence (cited with source/window/sample count). Without the config the
    behaviour is byte-identical to before.
    """
    bundle = collect_evidence(
        target, refs, sample_count, interval_ms, include_alarms,
        freshness_threshold_s=int(window.get("freshness_threshold_s", 60))
        if isinstance(window, dict) else 60,
    )
    historian = gather_pre_incident(window if isinstance(window, dict) else {}, refs)
    verdict = downtime_rca(
        window,
        alarms=bundle["alarms"],
        tags=bundle["tags"],
        dataflow=bundle["dataflow"],
        lead_window_s=lead_window_s,
        historian=historian,
    )
    verdict["collected_evidence"] = bundle["collected"]
    return verdict


def _sample_tag(target: Any, ref: str, sample_count: int, interval_ms: int) -> dict:
    """Sample one ref into a {ref, samples:[{value, good}]} series + config bounds."""
    n = max(1, min(int(sample_count), MAX_SAMPLES_PER_REF))
    interval = max(MIN_INTERVAL_MS, int(interval_ms))
    samples: list[dict] = []
    for i in range(n):
        try:
            value, _src_ts = _read_point(target, ref)
            samples.append({"value": value, "good": value is not None})
        except Exception as exc:  # noqa: BLE001 — a per-read failure is bad-quality data
            samples.append({"value": None, "good": False, "error": s(str(exc), 120)})
        if i < n - 1:
            time.sleep(interval / 1000.0)
    return {"ref": s(ref, 96), "samples": samples, **_config_bounds(target, ref)}


def _config_bounds(target: Any, ref: str) -> dict:
    """Pull warn/alarm bounds for a ref from endpoint config, if defined."""
    tag_for = getattr(target, "tag_for", None)
    if not callable(tag_for):
        return {}
    tag = tag_for(ref)
    if tag is None:
        return {}
    bounds = {
        "warn_high": getattr(tag, "warn_high", None),
        "alarm_high": getattr(tag, "alarm_high", None),
        "warn_low": getattr(tag, "warn_low", None),
        "alarm_low": getattr(tag, "alarm_low", None),
        "label": s(str(getattr(tag, "label", "") or ""), 64),
    }
    return {k: v for k, v in bounds.items() if v not in (None, "")}


def _collect_alarms(target: Any) -> list[dict]:
    """Surface active conditions as RCA alarm events (OPC-UA only; else empty)."""
    if getattr(target, "protocol", "") != "opcua":
        return []
    try:
        from iaiops.connectors.opcua.ops import read_alarms

        result = read_alarms(target)
    except Exception:  # noqa: BLE001 — alarm surfacing is best-effort, never fatal
        return []
    events: list[dict] = []
    for a in (result.get("active_alarms") or [])[:200]:
        name = s(str(a.get("browse_name", a.get("node_id", "alarm"))), 96)
        events.append({
            "source": name,
            "message": name,  # the browse-name carries the fault hint (…Fault/…Alarm)
            "state": "ACTIVE",
            # Address-space scan yields no event time — left untimed; the copilot
            # scores untimed evidence as real-but-not-time-localized.
            "timestamp": None,
        })
    return events


# Public alias: the ISA-18.2 alarm tools reuse the SAME best-effort acquisition
# path (OPC-UA active-condition scan) instead of inventing a second one.
collect_active_alarms = _collect_alarms

__all__ = ["collect_evidence", "downtime_rca_live", "collect_active_alarms"]
