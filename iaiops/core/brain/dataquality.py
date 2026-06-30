"""Data-quality watchdog — fleet-wide data-trust scorecard (READ-ONLY, pure).

Extends ``tag_health`` / ``historian_health`` from per-tag checks to a
cross-endpoint **rollup**: how trustworthy is the data this fleet is producing?
It scores each tag 0-100 on the dimensions that make OT data *untrustworthy* —
not whether a value is alarming (that's process health), but whether the value
can be believed at all:

  * **staleness** — the source stopped updating (last sample older than the tag's
    expected update interval).
  * **heartbeat liveness** (first-class) — a heartbeat/watchdog tag that should
    keep changing has flatlined → the upstream is dead even if comms look fine.
  * **bad quality** — the device/historian flags the sample BAD.
  * **flatline** — zero variance over the window (stuck sensor / frozen value).
  * **gaps** — missing samples in the time series.
  * **statistical anomaly** — an outlier that may be a data glitch.

It rolls these up per endpoint and across the fleet into scores, an issue
breakdown, and ranked worst-offenders — a single "can I trust this data" view
that also feeds the downtime root-cause copilot. Pure analysis over **provided**
feeds, so it is fully testable without a live plant.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.brain.diagnostics import _is_bad, _numeric_series, _parse_ts

MAX_FEEDS = 500
MAX_TAGS_PER_FEED = 2000
DEFAULT_STALENESS_S = 300.0
DEFAULT_GAP_FACTOR = 3.0  # a gap > expected_update_s × this counts as a data gap

# Per-issue score deductions (a tag starts at 100). Tuned so a single hard fault
# (dead heartbeat / all-bad / stale) drops a tag below the 'alarm' band on its own.
DEDUCTIONS = {
    "dead_heartbeat": 100,
    "bad_quality": 85,
    "stale": 60,
    "flatline": 35,
    "gappy": 30,
    "some_bad_quality": 25,
    "anomaly": 15,
}

# Score bands.
ALARM_BELOW = 40
WARN_BELOW = 75


def data_quality_scorecard(
    feeds: list[dict],
    default_staleness_s: float = DEFAULT_STALENESS_S,
    now: str | None = None,
) -> dict:
    """[READ] Fleet data-trust scorecard across endpoints' tag feeds.

    Each feed: ``{endpoint, staleness_s?, tags: [{ref, label?, samples,
    expected_update_s?, staleness_s?, gap_threshold_s?, flatline_after_s?,
    heartbeat?}]}`` where ``samples`` is a list of scalars or ``{value, good|
    quality, timestamp?}``. Staleness/gap thresholds are configurable per tag
    (``staleness_s`` / ``gap_threshold_s``) and per feed (``staleness_s``) so a
    slow daily counter is not judged like a 1Hz sensor; ``flatline_after_s`` flags
    a stuck value via its longest stall. ``now`` (ISO-8601) pins the staleness
    reference for deterministic results; omitted → current UTC. Returns per-tag
    scores, per-endpoint rollups, a fleet summary + issue breakdown, a first-class
    ``liveness`` section (dead-heartbeat / flatline), and ranked worst tags.
    """
    ref_now = _parse_ts(now) or datetime.now(tz=UTC)
    rows = [f for f in (feeds or [])[:MAX_FEEDS] if isinstance(f, dict)]
    if not rows:
        return {"error": "No feeds. Pass [{endpoint, tags:[{ref, samples:[...]}]}]."}

    endpoints: list[dict] = []
    all_tags: list[dict] = []
    issue_totals: dict[str, int] = {}
    for feed in rows:
        endpoint = s(str(feed.get("endpoint", "")), 64)
        # is-not-None so a feed pinning staleness_s: 0 keeps real-time strictness.
        feed_staleness = _first_num(feed.get("staleness_s"))
        if feed_staleness is None:
            feed_staleness = default_staleness_s
        tags = [t for t in (feed.get("tags") or [])[:MAX_TAGS_PER_FEED] if isinstance(t, dict)]
        assessed = [_assess_tag(endpoint, t, feed_staleness, ref_now) for t in tags]
        for a in assessed:
            for flag in a["flags"]:
                issue_totals[flag] = issue_totals.get(flag, 0) + 1
        all_tags.extend(assessed)
        endpoints.append(_rollup_endpoint(endpoint, assessed))

    fleet_score = _mean([e["score"] for e in endpoints])
    offenders = sorted((t for t in all_tags if t["score"] < 100), key=lambda t: t["score"])
    return {
        "evaluated_endpoints": len(endpoints),
        "evaluated_tags": len(all_tags),
        "fleet_score": fleet_score,
        "fleet_status": _status(fleet_score),
        "issue_breakdown": dict(sorted(issue_totals.items(), key=lambda kv: kv[1], reverse=True)),
        "liveness": _liveness_rollup(all_tags),
        "worst_endpoints": sorted(endpoints, key=lambda e: e["score"])[:5],
        "worst_tags": offenders[:20],
        "endpoints": endpoints,
        "reference_time": s(str(ref_now), 40),
        "note": "Data-trust score (0-100), NOT process health — it measures whether "
        "the data can be believed (stale / dead heartbeat / bad-quality / flatline / "
        "gaps), not whether a value is alarming.",
    }


def heartbeat_health(series: list[Any], max_interval_s: float | None = None) -> dict:
    """[READ] Is a heartbeat/watchdog tag still alive? (first-class liveness check).

    A heartbeat is expected to keep CHANGING (a counter incrementing or a bit
    toggling). Returns ``alive`` False when the series has flatlined (zero variance
    over >= 2 samples) — the upstream is dead even if comms/quality look fine. With
    timestamped samples and ``max_interval_s``, also reports the longest stall.
    """
    raw = list(series or [])
    values = _numeric_series(raw)
    if len(values) < 2:
        return {"alive": False, "samples": len(values),
                "reason": "need >= 2 numeric samples to judge a heartbeat"}
    spread = max(values) - min(values)
    changes = sum(1 for a, b in zip(values, values[1:]) if a != b)
    stall = _longest_stall(raw)
    alive = spread > 0 and changes > 0
    if alive and max_interval_s and stall is not None and stall > max_interval_s:
        alive = False
    return {
        "alive": alive,
        "samples": len(values),
        "distinct_transitions": changes,
        "spread": round(spread, 6),
        "longest_stall_s": stall,
        "max_interval_s": max_interval_s,
        "reason": "flatline — heartbeat not advancing" if spread == 0
        else ("stalled beyond max_interval_s" if not alive else "advancing normally"),
    }


# ─── per-tag assessment ──────────────────────────────────────────────────────


def _assess_tag(endpoint: str, tag: dict, feed_staleness_s: float, ref_now: datetime) -> dict:
    """Score one tag 0-100 over the data-trust dimensions; collect its flags.

    ``feed_staleness_s`` is the feed-level default staleness budget; a tag may
    override it (``staleness_s``) and the gap budget (``gap_threshold_s``).
    """
    ref = s(str(tag.get("ref", tag.get("tag", ""))), 96)
    raw = list(tag.get("samples", []) or [])
    values = _numeric_series(raw)
    staleness_s, gap_s = _thresholds(tag, feed_staleness_s)
    age = _last_age_s(raw, ref_now)
    stall = _longest_stall(raw)
    flags = _tag_flags(tag, raw, values, age, stall, staleness_s, gap_s)
    score = max(0, 100 - sum(DEDUCTIONS.get(f, 0) for f in flags))
    return {
        "endpoint": endpoint,
        "ref": ref,
        "label": s(str(tag.get("label", "")), 64),
        "heartbeat": bool(tag.get("heartbeat", False)),
        "samples": len(raw),
        "latest": values[-1] if values else None,
        "age_seconds": age,
        "staleness_s": staleness_s,
        "gap_threshold_s": gap_s,
        "longest_stall_s": stall,
        "flags": flags,
        "score": score,
        "status": _status(score),
    }


def _thresholds(tag: dict, feed_staleness_s: float) -> tuple[float, float]:
    """Resolve (staleness_s, gap_threshold_s) for one tag, honoring overrides.

    Precedence: tag ``staleness_s`` > tag ``expected_update_s`` > feed default.
    The gap budget defaults to staleness × DEFAULT_GAP_FACTOR unless the tag pins
    ``gap_threshold_s`` — so a slow daily counter is not judged like a 1Hz sensor.
    """
    # Use is-not-None precedence (NOT `or`): a deliberately-pinned 0 means "demand
    # real-time freshness" and must NOT fall through to a looser default.
    staleness = _first_num(
        tag.get("staleness_s"), tag.get("expected_update_s"), feed_staleness_s,
    )
    if staleness is None:
        staleness = feed_staleness_s
    pinned_gap = num(tag.get("gap_threshold_s"))
    gap = pinned_gap if pinned_gap is not None else staleness * DEFAULT_GAP_FACTOR
    return staleness, gap


def _first_num(*values: Any) -> float | None:
    """First value that parses to a number (treats 0 as a real value, not missing)."""
    for v in values:
        n = num(v)
        if n is not None:
            return n
    return None


def _tag_flags(
    tag: dict, raw: list[Any], values: list[float],
    age: float | None, stall: float | None, staleness_s: float, gap_s: float,
) -> list[str]:
    """Collect the data-trust flags for one tag (flatline/quality/staleness/gap)."""
    flags: list[str] = []
    if _is_flatlined(tag, values, stall):
        flags.append("dead_heartbeat" if tag.get("heartbeat") else "flatline")
    bad = sum(1 for it in raw if isinstance(it, dict) and _is_bad(it))
    if raw and bad == len(raw):
        flags.append("bad_quality")
    elif bad:
        flags.append("some_bad_quality")
    if age is not None and age > staleness_s:
        flags.append("stale")
    if _has_gap(raw, gap_s):
        flags.append("gappy")
    if _has_anomaly(values):
        flags.append("anomaly")
    return flags


def _is_flatlined(tag: dict, values: list[float], stall: float | None) -> bool:
    """Has the value stopped moving? A configurable ``flatline_after_s`` uses the
    longest stall (value should move but hasn't); else zero variance over the window.
    """
    if len(values) < 2:
        return False
    after = num(tag.get("flatline_after_s"))
    if after is not None and stall is not None:
        return stall > after
    return (max(values) - min(values)) <= 1e-9


def _rollup_endpoint(endpoint: str, tags: list[dict]) -> dict:
    """Aggregate per-tag scores into an endpoint-level data-trust rollup."""
    scores = [t["score"] for t in tags]
    counts = {"ok": 0, "warn": 0, "alarm": 0, "dead": 0}
    issue_counts: dict[str, int] = {}
    for t in tags:
        counts[t["status"]] += 1
        for f in t["flags"]:
            issue_counts[f] = issue_counts.get(f, 0) + 1
    score = _mean(scores) if scores else 100.0
    worst = min(tags, key=lambda t: t["score"]) if tags else None
    return {
        "endpoint": endpoint,
        "score": score,
        "status": _status(score),
        "tag_count": len(tags),
        "status_counts": counts,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda kv: kv[1], reverse=True)),
        "bad_quality_tags": issue_counts.get("bad_quality", 0)
        + issue_counts.get("some_bad_quality", 0),
        "worst_tag": {"ref": worst["ref"], "score": worst["score"], "flags": worst["flags"]}
        if worst else None,
    }


# ─── first-class liveness + cross-endpoint fleet rollup ──────────────────────


def _liveness_rollup(all_tags: list[dict]) -> dict:
    """Surface flatline / dead-heartbeat as explicit scored dimensions (not buried)."""
    dead = [_liveness_entry(t) for t in all_tags if "dead_heartbeat" in t["flags"]]
    flat = [_liveness_entry(t) for t in all_tags if "flatline" in t["flags"]]
    by_stall = lambda e: (e["longest_stall_s"] or 0.0, -e["score"])  # noqa: E731
    return {
        "dead_heartbeat_count": len(dead),
        "flatline_count": len(flat),
        "dead_heartbeats": sorted(dead, key=by_stall, reverse=True)[:20],
        "flatlines": sorted(flat, key=by_stall, reverse=True)[:20],
    }


def _liveness_entry(t: dict) -> dict:
    return {
        "endpoint": t["endpoint"], "ref": t["ref"], "heartbeat": t["heartbeat"],
        "longest_stall_s": t.get("longest_stall_s"), "score": t["score"],
    }


def data_quality_fleet_rollup(
    feeds: list[dict],
    default_staleness_s: float = DEFAULT_STALENESS_S,
    now: str | None = None,
    top_n: int = 10,
) -> dict:
    """[READ] Cross-endpoint fleet rollup: rank endpoints by worst tag + bad-quality.

    Builds on ``data_quality_scorecard`` to give a fleet-wide view: endpoints
    ranked by their single worst tag, bad-quality tag counts aggregated across
    every endpoint, and the first-class liveness rollup. Pure analysis.
    """
    card = data_quality_scorecard(feeds, default_staleness_s, now)
    if "error" in card:
        return card
    top = max(1, min(int(top_n or 10), MAX_FEEDS))
    endpoints = card["endpoints"]
    ranked = sorted(endpoints, key=_worst_tag_key)
    return {
        "evaluated_endpoints": card["evaluated_endpoints"],
        "evaluated_tags": card["evaluated_tags"],
        "fleet_score": card["fleet_score"],
        "fleet_status": card["fleet_status"],
        "endpoints_ranked_by_worst_tag": ranked[:top],
        "bad_quality_rollup": _fleet_bad_quality(endpoints, top),
        "liveness_rollup": card["liveness"],
        "issue_breakdown": card["issue_breakdown"],
        "reference_time": card["reference_time"],
        "note": "Fleet view: endpoints ranked by their single worst tag, plus "
        "bad-quality tag counts aggregated across every endpoint. Data-TRUST, "
        "not process health.",
    }


def _worst_tag_key(endpoint: dict) -> tuple[float, float]:
    """Sort key: lowest worst-tag score first, then lowest endpoint mean score."""
    worst = endpoint.get("worst_tag")
    return (worst["score"] if worst else 100.0, endpoint["score"])


def _fleet_bad_quality(endpoints: list[dict], top_n: int) -> dict:
    """Aggregate bad-quality tag counts across endpoints, ranked worst-first."""
    by_ep = [
        {
            "endpoint": e["endpoint"],
            "bad_quality_tags": e["bad_quality_tags"],
            "fully_bad": e["issue_counts"].get("bad_quality", 0),
            "partial_bad": e["issue_counts"].get("some_bad_quality", 0),
        }
        for e in endpoints if e["bad_quality_tags"]
    ]
    return {
        "total_bad_quality_tags": sum(e["bad_quality_tags"] for e in endpoints),
        "endpoints_affected": len(by_ep),
        "by_endpoint": sorted(by_ep, key=lambda x: x["bad_quality_tags"], reverse=True)[:top_n],
    }


# ─── helpers ─────────────────────────────────────────────────────────────────


def _status(score: float) -> str:
    if score <= 0:
        return "dead"
    if score < ALARM_BELOW:
        return "alarm"
    if score < WARN_BELOW:
        return "warn"
    return "ok"


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 100.0


def _last_age_s(raw: list[Any], ref_now: datetime) -> float | None:
    """Age (seconds) of the newest timestamped sample vs ``ref_now``, else None."""
    newest: datetime | None = None
    for it in raw:
        ts = _parse_ts(it.get("timestamp")) if isinstance(it, dict) else None
        if ts and (newest is None or ts > newest):
            newest = ts
    if newest is None:
        return None
    return round(max(0.0, (ref_now - newest).total_seconds()), 3)


def _has_gap(raw: list[Any], gap_threshold_s: float) -> bool:
    """True if consecutive timestamped samples are spaced beyond the threshold."""
    prev: datetime | None = None
    for it in raw:
        ts = _parse_ts(it.get("timestamp")) if isinstance(it, dict) else None
        if ts and prev and (ts - prev).total_seconds() > gap_threshold_s:
            return True
        if ts:
            prev = ts
    return False


def _has_anomaly(values: list[float]) -> bool:
    """A simple z-score outlier check (>3σ) over the window."""
    if len(values) < 4:
        return False
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    if stdev <= 0:
        return False
    return any(abs(v - mean) / stdev > 3.0 for v in values)


def _longest_stall(raw: list[Any]) -> float | None:
    """Longest run (seconds) where a heartbeat value did not change, if timestamped.

    Walks the timestamped samples; whenever the value stays equal to the previous
    one, the run is measured from the timestamp at which that constant value was
    first seen up to the current timestamp.
    """
    stamped = [
        (_parse_ts(it.get("timestamp")), num(it.get("value")))
        for it in raw if isinstance(it, dict)
    ]
    stamped = [(ts, v) for ts, v in stamped if ts is not None]
    if len(stamped) < 2:
        return None
    longest = 0.0
    run_start_ts, run_val = stamped[0]
    for ts, val in stamped[1:]:
        if val == run_val:
            longest = max(longest, (ts - run_start_ts).total_seconds())
        else:
            run_start_ts, run_val = ts, val
    return round(longest, 3)


__all__ = ["data_quality_scorecard", "data_quality_fleet_rollup", "heartbeat_health"]
