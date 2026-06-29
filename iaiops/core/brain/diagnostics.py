"""Cross-protocol intelligent troubleshooting (READ-ONLY, structured for agents).

Three analyzers, each returning multi-dimensional JSON an agent can visualize:

  * ``diagnose_dataflow`` — the #1 "no-data" triage. Probes each reachable hop of
    a target (connect → read → freshness → variance) and localizes the break into
    an actionable verdict: cannot connect (network/PLC down), comms OK but value
    stale (upstream/field/source), good status but flatline (sensor stuck), etc.
    We cannot reach real SCADA/historian tiers, so it diagnoses the layers we CAN
    reach and accepts an injected ``series`` for freshness/variance reasoning.
  * ``alarm_bad_actors`` — ISA-18.2 alarm-flood analysis over a list of alarm
    events: alarms/hour vs thresholds, Pareto top offenders, chattering, stale /
    standing alarms, priority distribution, and a flood verdict.
  * ``tag_health`` — bad-quality / flatline / out-of-range / statistical-anomaly
    offenders over a tag list + bounded samples, ranked by severity.

All inputs are validated; device/event text is sanitized.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from iaiops.core.brain._shared import num, s

# ISA-18.2 / EEMUA-191 alarm-rate guidance (alarms per operator per hour).
ISA_OK_PER_HOUR = 6
ISA_MANAGEABLE_PER_HOUR = 12
ISA_FLOOD_PER_HOUR = 30

MAX_EVENTS = 5000
MAX_SERIES = 2000
DEFAULT_CHATTER_WINDOW_S = 60
DEFAULT_STANDING_S = 86400  # 24h active → "standing/stale" alarm
DEFAULT_FRESHNESS_S = 60


# ─── shared helpers ──────────────────────────────────────────────────────────


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerant of a trailing Z), else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _numeric_series(series: list[Any]) -> list[float]:
    """Extract numeric values from a raw series of scalars or {value:...} dicts."""
    out: list[float] = []
    for item in (series or [])[:MAX_SERIES]:
        if isinstance(item, dict):
            v = num(item.get("value"))
        else:
            v = num(item)
        if v is not None:
            out.append(v)
    return out


# ─── 1. dataflow diagnosis ───────────────────────────────────────────────────


def diagnose_dataflow(
    target: Any,
    ref: str | None = None,
    freshness_threshold_s: int = DEFAULT_FRESHNESS_S,
    series: list[Any] | None = None,
    flatline_eps: float = 1e-9,
) -> dict:
    """[READ] Localize a 'no data' break across reachable hops of ``target``.

    Probes connect → read(ref) → freshness → variance and returns a verdict +
    per-hop detail + a recommended action. ``series`` (injected samples) enables
    flatline/variance reasoning when a live historian is out of reach.
    """
    hops: list[dict] = []
    protocol = getattr(target, "protocol", "")

    ok, detail = _probe_connect(target)
    hops.append({"hop": "connect", "protocol": s(protocol, 16), "ok": ok, "detail": s(detail, 200)})
    if not ok:
        return _verdict(
            hops, "cannot_connect",
            "Could not reach the endpoint — likely network path down, PLC/agent "
            "offline, wrong host/port, or a firewall.",
            "Check physical link, IP/port, and that the device's server/agent is "
            "running. Point at a simulator to isolate network vs device.",
        )

    read_desc: dict | None = None
    if ref:
        read_desc = _read_ref(target, ref)
        readable = "error" not in read_desc
        hops.append(
            {"hop": "read_tag", "ref": s(ref, 96), "ok": readable,
             "detail": s(str(read_desc.get("error", read_desc.get("value", ""))), 160)}
        )
        if not readable:
            return _verdict(
                hops, "comms_ok_value_unreadable",
                "Connected, but the tag/node could not be read — wrong address/node "
                "id, or the point does not exist on this device.",
                "Verify the ref against a browse/probe of the device's address space.",
            )

        good = read_desc.get("good")
        if good is False:
            return _verdict(
                hops, "comms_ok_bad_quality",
                "Connected and read, but the value's quality/status is BAD — a "
                "sensor, field wiring, or source-side fault.",
                "Inspect the field device / sensor and the source system feeding "
                "this tag; the comms path itself is healthy.",
            )

        fresh = _check_freshness(read_desc.get("source_timestamp"), freshness_threshold_s)
        hops.append({"hop": "freshness", **fresh})
        if fresh["evaluated"] and fresh["stale"]:
            return _verdict(
                hops, "comms_ok_value_stale",
                f"Connected with good status, but the value is STALE (age "
                f"{fresh['age_seconds']}s > {freshness_threshold_s}s) — the source/field "
                f"upstream has stopped updating this point.",
                "Trace upstream: the device serves the last value fine, so suspect "
                "the source/scanner/field signal that should refresh it.",
            )

    var = _check_variance(series, flatline_eps)
    if var["evaluated"]:
        hops.append({"hop": "variance", **var})
        if var["flatline"]:
            return _verdict(
                hops, "comms_ok_flatline",
                "Good status but the value is FLATLINE (zero variance over the "
                "window) — a stuck sensor or a frozen source value.",
                "Compare against a known-changing reference; a flatline with good "
                "quality usually means the source is stuck, not the comms.",
            )

    return _verdict(
        hops, "healthy",
        "All reachable hops look healthy (connected, readable, fresh, varying).",
        "No data-flow break found at the layers reachable from here.",
    )


def _verdict(hops: list[dict], verdict: str, diagnosis: str, action: str) -> dict:
    return {
        "verdict": verdict,
        "diagnosis": diagnosis,
        "recommended_action": action,
        "hops": hops,
        "note": "Diagnoses the layers reachable from this host (field/PLC/agent "
        "tier). SCADA/historian tiers we cannot reach are out of scope — pass a "
        "'series' to reason about freshness/variance from sampled data.",
    }


def _probe_connect(target: Any) -> tuple[bool, str]:
    """Lightweight per-protocol connectivity probe; returns (ok, detail)."""
    protocol = getattr(target, "protocol", "")
    try:
        if protocol == "opcua":
            from iaiops.connectors.opcua.ops import server_info

            info = server_info(target)
            return True, f"OPC-UA state={info.get('state')}"
        if protocol == "modbus":
            from iaiops.connectors.modbus.ops import modbus_read_holding

            modbus_read_holding(target, address=0, count=1)
            return True, "Modbus read OK"
        if protocol == "s7":
            from iaiops.connectors.s7.ops import s7_cpu_info

            info = s7_cpu_info(target)
            return True, f"S7 status={info.get('cpu_status')}"
        if protocol == "mc":
            from iaiops.connectors.mc.ops import mc_cpu_status

            info = mc_cpu_status(target)
            return True, f"MC cpu={info.get('cpu_type')}"
        if protocol == "mtconnect":
            from iaiops.connectors.mtconnect.ops import mtconnect_current

            cur = mtconnect_current(target)
            return True, f"MTConnect obs={cur.get('observation_count')}"
        if protocol == "mqtt":
            from iaiops.connectors.sparkplug.ops import mqtt_read_topic

            out = mqtt_read_topic(target, count=1, timeout_s=3)
            return True, f"MQTT msgs={out.get('message_count')}"
    except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
        return False, str(exc)[:200]
    return False, f"No connectivity probe for protocol '{protocol}'."


def _read_ref(target: Any, ref: str) -> dict:
    """Read one ref across protocols → a uniform {value, good, source_timestamp}."""
    protocol = getattr(target, "protocol", "")
    try:
        if protocol == "opcua":
            from iaiops.connectors.opcua.ops import read_node

            return read_node(target, ref)
        if protocol == "modbus":
            from iaiops.connectors.modbus.ops import modbus_read_holding

            r = modbus_read_holding(target, address=int(ref), count=1)
            return {"value": (r.get("decoded") or [None])[0], "good": True}
        if protocol == "s7":
            from iaiops.connectors.s7.ops import s7_read_many

            r = s7_read_many(target, [ref])
            items = r.get("items") or []
            return {"value": items[0]["value"] if items else None, "good": bool(items)}
        if protocol == "mc":
            from iaiops.connectors.mc.ops import mc_read_words

            r = mc_read_words(target, ref, count=1)
            words = r.get("words") or []
            return {"value": words[0] if words else None, "good": bool(words)}
    except Exception as exc:  # noqa: BLE001 — a read failure is a per-ref status
        return {"error": s(str(exc), 200)}
    return {"error": f"No per-ref read for protocol '{protocol}'."}


def _check_freshness(timestamp: Any, threshold_s: int) -> dict:
    """Classify a source timestamp's age against a freshness threshold."""
    ts = _parse_ts(timestamp)
    if ts is None:
        return {"evaluated": False, "stale": False, "age_seconds": None,
                "note": "No parseable per-sample timestamp at this layer."}
    now = datetime.now(tz=ts.tzinfo) if ts.tzinfo else datetime.now()  # noqa: DTZ005
    age = max(0.0, (now - ts).total_seconds())
    return {"evaluated": True, "stale": age > threshold_s, "age_seconds": round(age, 3)}


def _check_variance(series: list[Any] | None, eps: float) -> dict:
    """Detect a flatline (near-zero variance) over an injected numeric series."""
    values = _numeric_series(series or [])
    if len(values) < 2:
        return {"evaluated": False, "flatline": False, "samples": len(values)}
    spread = max(values) - min(values)
    return {
        "evaluated": True,
        "flatline": spread <= abs(eps),
        "samples": len(values),
        "spread": round(spread, 6),
        "stdev": round(statistics.pstdev(values), 6),
    }


def historian_health(
    series: list[Any],
    gap_threshold_s: float = 60.0,
    flatline_eps: float = 1e-9,
) -> dict:
    """[READ] Bad-tag / flatline / gap detection over a provided sample series.

    Each sample may be a scalar or ``{value, timestamp, quality|good}``. Detects
    bad-quality samples, a flatline (zero variance), and time gaps between
    consecutive samples larger than ``gap_threshold_s``. Pure analysis over the
    injected series — no live historian needed.
    """
    raw = list(series or [])[:MAX_SERIES]
    if not raw:
        return {"error": "Empty series. Pass a list of samples to evaluate."}
    values = _numeric_series(raw)
    bad_quality = sum(1 for it in raw if isinstance(it, dict) and _is_bad(it))
    gaps: list[dict] = []
    prev: datetime | None = None
    for it in raw:
        ts = _parse_ts(it.get("timestamp")) if isinstance(it, dict) else None
        if ts and prev:
            delta = (ts - prev).total_seconds()
            if delta > gap_threshold_s:
                gaps.append({"after": s(str(prev), 40), "gap_seconds": round(delta, 3)})
        if ts:
            prev = ts
    flatline = len(values) >= 2 and (max(values) - min(values)) <= abs(flatline_eps)
    verdict = "ok"
    if bad_quality and bad_quality == len(raw):
        verdict = "bad_tag"
    elif flatline:
        verdict = "flatline"
    elif gaps:
        verdict = "gappy"
    elif bad_quality:
        verdict = "degraded"
    return {
        "samples": len(raw),
        "numeric_samples": len(values),
        "bad_quality_count": bad_quality,
        "flatline": flatline,
        "gap_count": len(gaps),
        "gaps": gaps[:50],
        "stdev": round(statistics.pstdev(values), 6) if len(values) >= 2 else 0.0,
        "verdict": verdict,
    }


def _is_bad(sample: dict) -> bool:
    """A sample is bad-quality if quality looks bad or good/value is falsy/missing."""
    if "good" in sample:
        return sample["good"] is False
    q = str(sample.get("quality", "")).strip().lower()
    if q:
        return q not in ("good", "ok", "1", "true", "valid")
    return sample.get("value") is None


# ─── 2. ISA-18.2 alarm bad actors ────────────────────────────────────────────


def alarm_bad_actors(
    events: list[dict],
    window_minutes: float | None = None,
    chatter_window_s: float = DEFAULT_CHATTER_WINDOW_S,
    standing_s: float = DEFAULT_STANDING_S,
    top_n: int = 10,
) -> dict:
    """[READ] ISA-18.2 alarm-flood analysis over a list of alarm/condition events.

    Each event: ``{source, timestamp, priority?, state?}`` (state ACTIVE/RTN/ACK).
    Computes alarms/hour vs ISA-18.2 thresholds, Pareto top offenders (the ~20%
    of sources causing ~80% of alarms), chattering alarms (rapid repeats),
    stale/standing alarms (active beyond ``standing_s``), and the priority
    distribution. Returns ranked offenders + a flood verdict.
    """
    evts = [e for e in (events or [])[:MAX_EVENTS] if isinstance(e, dict)]
    if not evts:
        return {"error": "No events. Pass a list of {source, timestamp, priority?} dicts."}

    by_source: dict[str, list[dict]] = {}
    priority_dist: dict[str, int] = {}
    times: list[datetime] = []
    for e in evts:
        src = s(str(e.get("source", e.get("tag", "unknown"))), 96)
        by_source.setdefault(src, []).append(e)
        pri = s(str(e.get("priority", "unspecified")), 24)
        priority_dist[pri] = priority_dist.get(pri, 0) + 1
        ts = _parse_ts(e.get("timestamp"))
        if ts:
            times.append(ts)

    span_minutes = window_minutes
    if not span_minutes and len(times) >= 2:
        span_minutes = max((max(times) - min(times)).total_seconds() / 60.0, 1 / 60.0)
    span_minutes = span_minutes or (len(evts) / 60.0)  # fallback assume 1/s
    per_hour = round(len(evts) / (span_minutes / 60.0), 2) if span_minutes else float(len(evts))

    offenders = _rank_offenders(by_source, len(evts), chatter_window_s, standing_s)
    flood = _flood_verdict(per_hour)
    pareto = _pareto(offenders, len(evts))
    return {
        "event_count": len(evts),
        "window_minutes": round(span_minutes, 3),
        "alarms_per_hour": per_hour,
        "isa_18_2": {
            "ok_max": ISA_OK_PER_HOUR,
            "manageable_max": ISA_MANAGEABLE_PER_HOUR,
            "flood_min": ISA_FLOOD_PER_HOUR,
        },
        "flood_verdict": flood,
        "priority_distribution": priority_dist,
        "pareto_sources_for_80pct": pareto,
        "top_offenders": offenders[:max(1, int(top_n))],
        "chattering": [o["source"] for o in offenders if o["chattering"]],
        "standing": [o["source"] for o in offenders if o["standing"]],
    }


def _rank_offenders(
    by_source: dict[str, list[dict]], total: int, chatter_window_s: float, standing_s: float
) -> list[dict]:
    """Build per-source offender records ranked by alarm count desc."""
    out: list[dict] = []
    for src, group in by_source.items():
        stamps = sorted(t for t in (_parse_ts(e.get("timestamp")) for e in group) if t)
        chattering = _is_chattering(stamps, chatter_window_s)
        standing = _is_standing(group, stamps, standing_s)
        count = len(group)
        out.append(
            {
                "source": src,
                "count": count,
                "share_pct": round(100.0 * count / total, 2) if total else 0.0,
                "chattering": chattering,
                "standing": standing,
            }
        )
    out.sort(key=lambda o: o["count"], reverse=True)
    return out


def _is_chattering(stamps: list[datetime], window_s: float) -> bool:
    """True if >=3 transitions occur within ``window_s`` (rapid repeat)."""
    if len(stamps) < 3:
        return False
    for i in range(len(stamps) - 2):
        if (stamps[i + 2] - stamps[i]).total_seconds() <= window_s:
            return True
    return False


def _is_standing(group: list[dict], stamps: list[datetime], standing_s: float) -> bool:
    """True if the alarm has been ACTIVE longer than ``standing_s`` without return."""
    states = [str(e.get("state", "")).strip().upper() for e in group]
    if any(st in ("RTN", "RETURN", "NORMAL", "CLEARED") for st in states):
        return False
    if not any(st in ("ACTIVE", "ALM", "ALARM", "") for st in states):
        return False
    if stamps:
        age = (datetime.now(tz=stamps[0].tzinfo) if stamps[0].tzinfo
               else datetime.now()).timestamp() - stamps[0].timestamp()  # noqa: DTZ005
        return age > standing_s
    return False


def _flood_verdict(per_hour: float) -> str:
    """Map alarms/hour to an ISA-18.2 band."""
    if per_hour > ISA_FLOOD_PER_HOUR:
        return "flood"
    if per_hour > ISA_MANAGEABLE_PER_HOUR:
        return "over_target"
    if per_hour > ISA_OK_PER_HOUR:
        return "manageable"
    return "ok"


def _pareto(offenders: list[dict], total: int) -> list[str]:
    """The smallest set of sources that together cause >=80% of alarms."""
    cum = 0
    picked: list[str] = []
    for o in offenders:
        if total and cum / total >= 0.8:
            break
        picked.append(o["source"])
        cum += o["count"]
    return picked


# ─── 3. tag health / anomaly offenders ───────────────────────────────────────


def tag_health(tags: list[dict], thresholds: dict | None = None) -> dict:
    """[READ] Rank tag offenders by bad-quality / flatline / range / anomaly.

    Each tag: ``{ref, label?, samples: [..], warn_high?, alarm_high?, ...}`` where
    ``samples`` is a list of scalars or ``{value, good|quality}`` dicts. Detects:
    bad quality, flatline (zero variance), out-of-range vs warn/alarm bounds, and
    statistical anomalies (z-score and IQR). Returns offenders ranked by severity.
    """
    rows = [t for t in (tags or []) if isinstance(t, dict)]
    if not rows:
        return {"error": "No tags. Pass [{ref, samples:[...], warn_high?, ...}]."}
    results: list[dict] = []
    for t in rows:
        ref = s(str(t.get("ref", t.get("tag", ""))), 96)
        bounds = (thresholds or {}).get(ref, t)
        label = s(str(t.get("label", "")), 64)
        results.append(_assess_tag(ref, label, t.get("samples", []), bounds))
    offenders = [r for r in results if r["severity"] > 0]
    offenders.sort(key=lambda r: r["severity"], reverse=True)
    worst = max((r["severity"] for r in results), default=0)
    overall = "alarm" if worst >= 3 else "warn" if worst >= 1 else "ok"
    return {
        "evaluated": len(results),
        "overall": overall,
        "offender_count": len(offenders),
        "offenders": offenders,
        "results": results,
    }


def _assess_tag(ref: str, label: str, samples: list[Any], bounds: dict) -> dict:
    """Assess one tag's samples → flags + a 0..3 severity score."""
    raw = list(samples or [])[:MAX_SERIES]
    values = _numeric_series(raw)
    bad_quality = sum(1 for it in raw if isinstance(it, dict) and _is_bad(it))
    flags: list[str] = []
    severity = 0
    if raw and bad_quality == len(raw):
        flags.append("bad_quality")
        severity = max(severity, 3)
    elif bad_quality:
        flags.append("some_bad_quality")
        severity = max(severity, 1)
    if len(values) >= 2 and (max(values) - min(values)) <= 1e-9:
        flags.append("flatline")
        severity = max(severity, 2)
    latest = values[-1] if values else None
    range_status = _range_status(latest, bounds)
    if range_status == "alarm":
        flags.append("out_of_range_alarm")
        severity = max(severity, 3)
    elif range_status == "warn":
        flags.append("out_of_range_warn")
        severity = max(severity, 1)
    anomalies = _anomalies(values)
    if anomalies:
        flags.append("statistical_anomaly")
        severity = max(severity, 2)
    return {
        "ref": ref,
        "label": label,
        "samples": len(values),
        "latest": latest,
        "flags": flags,
        "anomaly_count": len(anomalies),
        "severity": severity,
    }


def _range_status(value: float | None, bounds: dict) -> str:
    """Classify a value against warn/alarm bounds in ``bounds`` (ok if none)."""
    if value is None:
        return "unknown"
    from iaiops.core.runtime.config import MonitorTag

    tag = MonitorTag(
        ref="",
        warn_high=_optf(bounds.get("warn_high")),
        alarm_high=_optf(bounds.get("alarm_high")),
        warn_low=_optf(bounds.get("warn_low")),
        alarm_low=_optf(bounds.get("alarm_low")),
    )
    return tag.classify(value)


def _optf(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _anomalies(values: list[float]) -> list[dict]:
    """Flag statistical outliers via z-score (>3σ) and IQR (1.5·IQR fence)."""
    if len(values) < 4:
        return []
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    ordered = sorted(values)
    q1 = ordered[len(ordered) // 4]
    q3 = ordered[(3 * len(ordered)) // 4]
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out: list[dict] = []
    for v in values:
        z = abs(v - mean) / stdev if stdev > 0 else 0.0
        if (stdev > 0 and z > 3.0) or (iqr > 0 and (v < lo or v > hi)):
            out.append({"value": v, "z_score": round(z, 3)})
    return out[:50]


__all__ = [
    "diagnose_dataflow",
    "historian_health",
    "alarm_bad_actors",
    "tag_health",
]
