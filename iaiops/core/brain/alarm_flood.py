"""ISA-18.2 alarm-flood deepening (READ-ONLY, pure analysis).

Deepens ``diagnostics.alarm_bad_actors`` with the ISA-18.2 flood/chattering/
standing metrics a rationalization program actually needs:

  * ``detect_floods`` — flood *episodes* (start/end/count/peak rate/top
    contributors) per ISA-18.2: a flood begins when the annunciation rate
    reaches >=10 alarms per 10 minutes per operator position and ends when the
    rate falls back below the end threshold (default: half the start threshold).
  * ``chattering_alarms`` — alarms that repeatedly cycle ACTIVE→CLEARED
    (ISA-18.2 chattering), with cycles/hour per source.
  * ``stale_standing_alarms`` — alarms continuously active beyond a threshold
    (default 24 h) with no return-to-normal, i.e. standing/stale alarms.
  * ``flood_summary`` — percent-time-in-flood plus average/peak alarm rate vs
    the ISA-18.2 steady-state target (~1-2 alarms per 10 minutes), with honest
    "insufficient data" handling when the event span is too thin to judge.
  * ``rationalization_worksheet`` — per-alarm rows (count, share, chattering?,
    in-flood?, recommendation stub) suitable for CSV export.

Every function is pure over a list of normalized alarm events
``{source, timestamp, message?, state?}`` — the same event shape (and thus the
same acquisition path) as ``alarm_bad_actors``. No I/O happens here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from iaiops.core.brain._shared import s
from iaiops.core.brain.diagnostics import MAX_EVENTS, _parse_ts

# ISA-18.2 flood definition: >=10 annunciated alarms per 10 min per operator.
FLOOD_WINDOW_S = 600
FLOOD_THRESHOLD = 10
# ISA-18.2 steady-state target: ~1 (max ~2) alarms per 10 minutes.
TARGET_AVG_PER_10MIN = 2.0
# ISA-18.2 target: percent of time in flood should be < ~1%.
TARGET_FLOOD_TIME_PCT = 1.0

# Chattering: repeated ACTIVE→CLEARED cycles; >=3 cycles inside any 1 minute is
# the classic ISA-18.2 TR definition — expressed here as cycles within a window.
CHATTER_MIN_CYCLES = 3
CHATTER_WINDOW_S = 60.0

DEFAULT_STALE_AFTER_S = 86400  # 24h continuously active → standing/stale

MAX_EPISODES = 50
MAX_CONTRIBUTORS = 5
MAX_WORKSHEET_ROWS = 500

_ACTIVE_STATES = frozenset({"ACTIVE", "ALM", "ALARM", ""})
_CLEARED_STATES = frozenset({"RTN", "RETURN", "NORMAL", "CLEARED", "INACTIVE"})


@dataclass(frozen=True)
class FloodEpisode:
    """One ISA-18.2 alarm-flood episode over the analyzed event stream."""

    start: str
    end: str
    duration_s: float
    count: int
    peak_count_in_window: int
    peak_rate_per_10min: float
    top_contributors: tuple[dict, ...]


@dataclass(frozen=True)
class ChatteringAlarm:
    """A source cycling ACTIVE→CLEARED repeatedly (ISA-18.2 chattering)."""

    source: str
    cycles: int
    cycles_per_hour: float
    max_cycles_in_window: int
    window_s: float


@dataclass(frozen=True)
class StaleAlarm:
    """An alarm continuously active beyond the stale threshold (standing)."""

    source: str
    active_since: str
    active_for_s: float


@dataclass(frozen=True)
class WorksheetRow:
    """One alarm-rationalization worksheet row (CSV-exportable)."""

    alarm_id: str
    count: int
    pct_of_total: float
    chattering: bool
    in_flood: bool
    recommendation: str


WORKSHEET_COLUMNS = (
    "alarm_id",
    "count",
    "pct_of_total",
    "chattering",
    "in_flood",
    "recommendation",
)


# ─── normalization ───────────────────────────────────────────────────────────


def _norm_events(events: list | None) -> list[tuple[datetime, str, str]]:
    """Normalize raw events → sorted ``(ts, source, state)`` tuples.

    Events without a parseable timestamp are dropped (rate math needs time);
    the state is upper-cased so ACTIVE/RTN variants compare uniformly.
    """
    out: list[tuple[datetime, str, str]] = []
    for e in (events or [])[:MAX_EVENTS]:
        if not isinstance(e, dict):
            continue
        ts = _parse_ts(e.get("timestamp", e.get("ts")))
        if ts is None:
            continue
        src = s(str(e.get("source", e.get("tag", "unknown"))), 96)
        state = str(e.get("state", "")).strip().upper()
        out.append((ts, src, state))
    out.sort(key=lambda t: t[0])
    return out


def _activations(norm: list[tuple[datetime, str, str]]) -> list[tuple[datetime, str]]:
    """Only new-alarm annunciations count toward flood rates (not RTN/ACK)."""
    return [(ts, src) for ts, src, state in norm if state in _ACTIVE_STATES]


# ─── 1. flood episodes ───────────────────────────────────────────────────────


def detect_floods(
    events: list,
    window_s: float = FLOOD_WINDOW_S,
    threshold: int = FLOOD_THRESHOLD,
    end_threshold: int | None = None,
    max_episodes: int = MAX_EPISODES,
) -> list[FloodEpisode]:
    """[READ] Detect ISA-18.2 alarm-flood episodes in an event stream.

    A flood starts when >= ``threshold`` annunciations land inside a trailing
    ``window_s`` window (ISA-18.2: 10 alarms / 10 min / operator) and ends when
    the trailing-window count drops below ``end_threshold`` (default: half the
    start threshold, ISA-18.2's "rate returns below 5/10 min") or the stream
    goes quiet for a full window. Returns chronological episodes with peak rate
    and top contributing sources.
    """
    if window_s <= 0 or threshold < 1:
        raise ValueError("window_s must be > 0 and threshold >= 1.")
    end_at = max(1, threshold // 2) if end_threshold is None else max(1, int(end_threshold))
    acts = _activations(_norm_events(events))
    if not acts:
        return []

    episodes: list[FloodEpisode] = []
    window: list[tuple[datetime, str]] = []  # trailing window of (ts, source)
    in_flood = False
    ep_events: list[tuple[datetime, str]] = []
    ep_start: datetime | None = None
    peak = 0

    def close(end_ts: datetime) -> None:
        nonlocal in_flood, ep_events, ep_start, peak
        if ep_start is not None and len(episodes) < max(1, int(max_episodes)):
            episodes.append(_episode(ep_start, end_ts, ep_events, peak, window_s))
        in_flood, ep_events, ep_start, peak = False, [], None, 0

    for ts, src in acts:
        # Flood ends if the stream goes quiet for a whole window.
        if in_flood and window and (ts - window[-1][0]).total_seconds() > window_s:
            close(window[-1][0])
        window = [(t, sr) for t, sr in window if (ts - t).total_seconds() <= window_s]
        window.append((ts, src))
        count = len(window)
        if not in_flood and count >= threshold:
            in_flood = True
            ep_start = window[0][0]
            ep_events = list(window)
            peak = count
        elif in_flood:
            ep_events.append((ts, src))
            peak = max(peak, count)
            if count < end_at:
                close(ts)
    if in_flood and window:
        close(window[-1][0])
    return episodes


def _episode(
    start: datetime,
    end: datetime,
    evts: list[tuple[datetime, str]],
    peak: int,
    window_s: float,
) -> FloodEpisode:
    counts: dict[str, int] = {}
    for _, src in evts:
        counts[src] = counts.get(src, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:MAX_CONTRIBUTORS]
    return FloodEpisode(
        start=start.isoformat(),
        end=end.isoformat(),
        duration_s=round(max(0.0, (end - start).total_seconds()), 3),
        count=len(evts),
        peak_count_in_window=peak,
        peak_rate_per_10min=round(peak * 600.0 / window_s, 2),
        top_contributors=tuple({"source": src, "count": n} for src, n in top),
    )


# ─── 2. chattering ───────────────────────────────────────────────────────────


def chattering_alarms(
    events: list,
    min_cycles: int = CHATTER_MIN_CYCLES,
    window_s: float = CHATTER_WINDOW_S,
) -> list[ChatteringAlarm]:
    """[READ] Alarms cycling ACTIVE→CLEARED repeatedly (ISA-18.2 chattering).

    A *cycle* is an activation followed by a return-to-normal for the same
    source. A source chatters when >= ``min_cycles`` complete cycles land inside
    any ``window_s`` window (default: 3 cycles / 60 s, the ISA-18.2 TR rule).
    Also reports cycles/hour over the source's observed span. Sorted worst-first.
    """
    if min_cycles < 1 or window_s <= 0:
        raise ValueError("min_cycles must be >= 1 and window_s > 0.")
    norm = _norm_events(events)
    by_source: dict[str, list[tuple[datetime, str]]] = {}
    for ts, src, state in norm:
        by_source.setdefault(src, []).append((ts, state))

    out: list[ChatteringAlarm] = []
    for src, seq in by_source.items():
        cycle_times = _cycle_completions(seq)
        if not cycle_times:
            continue
        max_in_window = _max_in_window(cycle_times, window_s)
        if max_in_window < min_cycles:
            continue
        span_s = max((seq[-1][0] - seq[0][0]).total_seconds(), 1.0)
        out.append(
            ChatteringAlarm(
                source=src,
                cycles=len(cycle_times),
                cycles_per_hour=round(len(cycle_times) * 3600.0 / span_s, 2),
                max_cycles_in_window=max_in_window,
                window_s=window_s,
            )
        )
    out.sort(key=lambda c: (c.max_cycles_in_window, c.cycles), reverse=True)
    return out


def _cycle_completions(seq: list[tuple[datetime, str]]) -> list[datetime]:
    """Times at which an ACTIVE→CLEARED cycle completed for one source."""
    times: list[datetime] = []
    active = False
    for ts, state in seq:
        if state in _CLEARED_STATES:
            if active:
                times.append(ts)
            active = False
        elif state in _ACTIVE_STATES:
            active = True
    return times


def _max_in_window(times: list[datetime], window_s: float) -> int:
    """Max number of ``times`` falling inside any trailing window of window_s."""
    best = 0
    lo = 0
    for hi, ts in enumerate(times):
        while (ts - times[lo]).total_seconds() > window_s:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


# ─── 3. stale / standing alarms ──────────────────────────────────────────────


def stale_standing_alarms(
    events: list,
    now: datetime | str,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> list[StaleAlarm]:
    """[READ] Alarms continuously active beyond ``stale_after_s`` (standing).

    Per source, the last activation with no subsequent return-to-normal marks it
    still active; if it has been active longer than ``stale_after_s`` as of
    ``now`` (ISO-8601 or datetime — explicit, so the check is deterministic),
    it is a standing/stale alarm. Sorted oldest-first.
    """
    ref = _parse_ts(now)
    if ref is None:
        raise ValueError("now must be a datetime or ISO-8601 timestamp.")
    if stale_after_s <= 0:
        raise ValueError("stale_after_s must be > 0.")
    latest: dict[str, tuple[datetime, bool]] = {}  # source -> (last activation, active?)
    for ts, src, state in _norm_events(events):
        if state in _CLEARED_STATES:
            prev = latest.get(src)
            latest[src] = (prev[0] if prev else ts, False)
        elif state in _ACTIVE_STATES:
            prev = latest.get(src)
            # Keep the ORIGINAL activation time across re-annunciations while active.
            since = prev[0] if prev and prev[1] else ts
            latest[src] = (since, True)
    out = [
        StaleAlarm(
            source=src,
            active_since=since.isoformat(),
            active_for_s=round((ref - since).total_seconds(), 3),
        )
        for src, (since, active) in latest.items()
        if active and (ref - since).total_seconds() > stale_after_s
    ]
    out.sort(key=lambda a: a.active_for_s, reverse=True)
    return out


# ─── 4. flood summary vs ISA-18.2 targets ────────────────────────────────────


def flood_summary(
    events: list,
    window_s: float = FLOOD_WINDOW_S,
    threshold: int = FLOOD_THRESHOLD,
) -> dict:
    """[READ] Percent-time-in-flood + average/peak rate vs ISA-18.2 targets.

    ISA-18.2 steady-state target is ~1 (max ~2) alarms per 10 minutes per
    operator, with < ~1% of time in flood. Needs a span of at least one window
    of timestamped events; anything thinner returns an honest
    ``insufficient_data`` result instead of a fabricated rate.
    """
    acts = _activations(_norm_events(events))
    if len(acts) < 2:
        return {
            "insufficient_data": True,
            "reason": "Need >=2 timestamped annunciations to compute a rate.",
            "event_count": len(acts),
        }
    span_s = (acts[-1][0] - acts[0][0]).total_seconds()
    if span_s < window_s:
        return {
            "insufficient_data": True,
            "reason": (
                f"Event span {round(span_s, 1)}s is shorter than one analysis "
                f"window ({window_s}s) — rates would be unrepresentative."
            ),
            "event_count": len(acts),
            "span_s": round(span_s, 3),
        }
    episodes = detect_floods(acts_to_events(acts), window_s, threshold)
    flood_time_s = sum(e.duration_s for e in episodes)
    avg_per_10min = len(acts) * 600.0 / span_s
    peak = max((e.peak_count_in_window for e in episodes), default=0)
    if not episodes:
        peak = _max_in_window([t for t, _ in acts], window_s)
    peak_per_10min = peak * 600.0 / window_s
    pct_in_flood = 100.0 * flood_time_s / span_s
    return {
        "insufficient_data": False,
        "event_count": len(acts),
        "span_s": round(span_s, 3),
        "flood_episodes": len(episodes),
        "time_in_flood_s": round(flood_time_s, 3),
        "percent_time_in_flood": round(pct_in_flood, 3),
        "avg_alarms_per_10min": round(avg_per_10min, 3),
        "peak_alarms_per_10min": round(peak_per_10min, 2),
        "isa_18_2_targets": {
            "avg_per_10min_max": TARGET_AVG_PER_10MIN,
            "percent_time_in_flood_max": TARGET_FLOOD_TIME_PCT,
            "flood_definition": f">={threshold} alarms per {int(window_s)}s",
        },
        "meets_avg_target": avg_per_10min <= TARGET_AVG_PER_10MIN,
        "meets_flood_time_target": pct_in_flood <= TARGET_FLOOD_TIME_PCT,
    }


def acts_to_events(acts: list[tuple[datetime, str]]) -> list[dict]:
    """Re-shape normalized activations back into event dicts (helper, pure)."""
    return [{"source": src, "timestamp": ts.isoformat(), "state": "ACTIVE"} for ts, src in acts]


# ─── 5. rationalization worksheet ────────────────────────────────────────────


def rationalization_worksheet(
    events: list,
    window_s: float = FLOOD_WINDOW_S,
    threshold: int = FLOOD_THRESHOLD,
    max_rows: int = MAX_WORKSHEET_ROWS,
) -> list[WorksheetRow]:
    """[READ] Per-alarm rationalization rows (ISA-18.2 documentation aid).

    One row per alarm source, count-descending: total count, share of all
    annunciations, whether it chatters, whether it contributed to a flood
    episode, and a recommendation stub for the rationalization team.
    """
    acts = _activations(_norm_events(events))
    total = len(acts)
    if not total:
        return []
    chattering = {c.source for c in chattering_alarms(events)}
    in_flood: set[str] = set()
    for ep in detect_floods(events, window_s, threshold):
        in_flood.update(c["source"] for c in ep.top_contributors)
    counts: dict[str, int] = {}
    for _, src in acts:
        counts[src] = counts.get(src, 0) + 1
    rows = [
        WorksheetRow(
            alarm_id=src,
            count=n,
            pct_of_total=round(100.0 * n / total, 2),
            chattering=src in chattering,
            in_flood=src in in_flood,
            recommendation=_recommendation(src in chattering, src in in_flood, 100.0 * n / total),
        )
        for src, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return rows[: max(1, int(max_rows))]


def _recommendation(chattering: bool, in_flood: bool, share_pct: float) -> str:
    if chattering:
        return (
            "Add on/off delay or deadband; review setpoint (ISA-18.2 "
            "chattering — top rationalization candidate)."
        )
    if in_flood and share_pct >= 5.0:
        return (
            "Flood contributor — evaluate state-based/dynamic suppression "
            "and alarm priority during upsets."
        )
    if share_pct >= 10.0:
        return "High share of total load — verify setpoint, priority, and consequence."
    return "Retain; monitor in the next rationalization review."


def worksheet_rows_as_dicts(rows: list[WorksheetRow]) -> list[dict]:
    """JSON/CSV-friendly dict view of worksheet rows (column order fixed)."""
    return [asdict(r) for r in rows]


# ─── 6. combined report (tool-facing, still pure) ────────────────────────────


def alarm_flood_report(
    events: list,
    window_s: float = FLOOD_WINDOW_S,
    threshold: int = FLOOD_THRESHOLD,
    now: datetime | str | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    max_episodes: int = 20,
    max_rows: int = 50,
) -> dict:
    """[READ] One bounded ISA-18.2 deep report: floods + chattering + stale + summary.

    Pure composition of the detectors above with explicit output caps; the
    ``truncated`` flags say when caps bit. ``now`` (default: last event time)
    anchors the stale-alarm check deterministically.
    """
    norm = _norm_events(events)
    if not norm:
        return {"error": "No timestamped events. Pass [{source, timestamp, state?}, ...]."}
    ref: datetime | str = now if now is not None else norm[-1][0] + timedelta(seconds=1)
    episodes = detect_floods(events, window_s, threshold)
    chatter = chattering_alarms(events)
    stale = stale_standing_alarms(events, ref, stale_after_s)
    rows = rationalization_worksheet(events, window_s, threshold)
    cap_ep, cap_rows = max(1, int(max_episodes)), max(1, int(max_rows))
    return {
        "event_count": len(norm),
        "summary": flood_summary(events, window_s, threshold),
        "flood_episodes": [asdict(e) for e in episodes[:cap_ep]],
        "chattering": [asdict(c) for c in chatter[:cap_rows]],
        "stale_standing": [asdict(a) for a in stale[:cap_rows]],
        "worksheet_preview": worksheet_rows_as_dicts(rows[:cap_rows]),
        "truncated": {
            "flood_episodes": len(episodes) > cap_ep,
            "chattering": len(chatter) > cap_rows,
            "stale_standing": len(stale) > cap_rows,
            "worksheet": len(rows) > cap_rows,
        },
    }


def alarm_cascade(events: list, window_s: float = 60.0, min_cascade: int = 2) -> dict:
    """Collapse an alarm flood into cascades + the likely FIRST-OUT root of each (READ-ONLY, pure).

    An operator flooded with 100+ alarms in 10 min needs "which one to look at first". This groups
    annunciations into temporal cascades (a new cascade starts after a quiet gap > ``window_s``) and
    reports the **first-out** alarm (earliest in the burst) as the likely root, plus the downstream
    members and any chattering sources. First-out is a transparent *heuristic* root cited by
    timestamp — NOT a causal claim (use downtime_root_cause for causality). Advisory.
    """
    acts = _activations(_norm_events(events))
    if not acts:
        return {"cascade_count": 0, "total_activations": 0, "cascades": []}
    cascades: list[list[tuple[datetime, str]]] = [[acts[0]]]
    for prev, item in zip(acts, acts[1:]):
        if (item[0] - prev[0]).total_seconds() > window_s:
            cascades.append([item])
        else:
            cascades[-1].append(item)

    out: list[dict] = []
    for group in cascades:
        if len(group) < int(min_cascade):
            continue
        root_ts, root_src = group[0]
        counts: dict[str, int] = {}
        for _ts, src in group:
            counts[src] = counts.get(src, 0) + 1
        out.append(
            {
                "root": {"source": root_src, "ts": root_ts.isoformat()},
                "size": len(group),
                "distinct_sources": len(counts),
                "span_s": round((group[-1][0] - group[0][0]).total_seconds(), 2),
                "members": list(counts.keys())[:100],
                "chattering": [src for src, n in counts.items() if n > 1][:50],
            }
        )
    out.sort(key=lambda c: c["size"], reverse=True)
    return {"cascade_count": len(out), "total_activations": len(acts), "cascades": out[:50]}


__all__ = [
    "FloodEpisode",
    "ChatteringAlarm",
    "StaleAlarm",
    "WorksheetRow",
    "WORKSHEET_COLUMNS",
    "detect_floods",
    "chattering_alarms",
    "stale_standing_alarms",
    "flood_summary",
    "alarm_cascade",
    "rationalization_worksheet",
    "worksheet_rows_as_dicts",
    "alarm_flood_report",
]
