"""Trigger · Symptom · Propagation · Recovery — a re-ordering, not a story.

HLD §13.7, investigation step 05. Of the eight steps this is the one that looks
most like intelligence and is the easiest to turn into fiction, so it is fenced:

**Every line cites an evidence id.** No new facts are produced. Each entry is one
observed CHANGE and says which sample it came from, so a reader can go back to
it. Nothing is interpolated: a value nobody sampled never appears.

**Propagation comes only from declared relations** (D25). On a line, everything
downstream of a stoppage correlates with it — that correlation is a *guarantee*,
not evidence, and inferring propagation from timing would manufacture a causal
chain out of it. Time order still applies inside a declared edge: a downstream
change that happened BEFORE the trigger is not propagation either, or a declared
relation would launder any co-occurrence.

**The four labels need declared semantics.** "The first change is the Trigger" is
only true if you know which value means running. Without a declared run-state
tag this returns a plain ordered change list and says why — useful on its own,
and claiming nothing it cannot support.

**Degradation is explicit.** With no relations it produces a single-asset
timeline and labels itself that way. A four-segment timeline that silently
dropped propagation would read as "nothing propagated".

[PURE] No I/O. Rows come from the caller.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, parse_ts, s

#: Enough to see a shift's worth of transitions; short enough that a mis-declared
#: analogue tag cannot turn a timeline into a data dump.
MAX_ENTRIES = 500

#: True when the cap actually cut something off. Silent truncation is how a
#: partial timeline reads as a complete one.
_TRUNCATED = "truncated"

#: A tag that changes in more than this share of its own samples carries no
#: event information — a production counter changes at 100%, a run-state at a
#: few percent. Measured against the real cross-LAN collection, where the
#: counters alone produced 500 entries and pushed the actual trigger off the
#: end of the list.
#: Measured, not guessed. On the real cross-LAN collection (333 samples per tag,
#: 200 ms, a 90-second window):
#:
#:     tag 0  (run state)      7 changes / 333 = 0.02
#:     tag 10 (part counter) 255 changes / 333 = 0.77
#:     tag 11 (good counter) 255 changes / 333 = 0.77
#:
#: The gap between a state and a counter is enormous, so the threshold sits in
#: the middle of it rather than at either edge. 0.9 was the first value tried and
#: it let both counters through — 500 entries, the cap hit, the trigger buried
#: under 361 "symptoms".
CHATTER_SHARE = 0.5

#: Below this many samples, a change rate says nothing and nothing is excluded.
MIN_SAMPLES_TO_JUDGE = 10

TRIGGER = "trigger"
SYMPTOM = "symptom"
PROPAGATION = "propagation"
RECOVERY = "recovery"

__all__ = ["build_timeline", "TRIGGER", "SYMPTOM", "PROPAGATION", "RECOVERY", "MAX_ENTRIES"]


def build_timeline(
    window: dict[str, Any],
    rows: list[dict[str, Any]],
    run_state_tag: dict[str, Any] | None = None,
    downstream: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Re-order observed changes into a timeline. Adds no facts.

    ``run_state_tag`` is ``{ref, running_when}`` as declared in the config;
    without it the four segments are refused. ``downstream`` is the declared
    line order (nearest first) — without it, nothing is called propagation.
    """
    event_tags, flooding = _event_tags(list(rows or ()), str((run_state_tag or {}).get("ref", "")))
    changes = _changes([r for r in rows or () if str(r.get("tag", "")) in event_tags])
    if not changes:
        return {
            "window": dict(window or {}),
            "segmented": False,
            "scope": "single_asset",
            "entries": [],
            "note": "no value changes in this window — nothing to place on a timeline",
        }

    primary = str((window or {}).get("asset") or "")
    if not run_state_tag:
        return {
            "window": dict(window or {}),
            "segmented": False,
            "scope": "single_asset",
            "entries": [_entry(c, "") for c in changes],
            "note": (
                (
                    f"excluded (changes on nearly every sample): {', '.join(flooding)} · "
                    if flooding
                    else ""
                )
                + "changes in time order, unlabelled: the four segments need a tag "
                "declared with role 'run_state' so that which value means running "
                "comes from the config rather than from a guess"
            ),
        }

    trigger = _first_stop(changes, run_state_tag, primary)
    recovery = _first_recovery(changes, run_state_tag, primary, trigger)
    entries = [
        _entry(change, _segment(change, trigger, recovery, primary, downstream))
        for change in changes
    ]
    notes = []
    if changes and changes[-1].get(_TRUNCATED):
        notes.append(
            f"TRUNCATED at {MAX_ENTRIES} entries — later changes in this window are "
            "not shown; narrow the window to see them"
        )
    if flooding:
        notes.append(
            f"excluded from the timeline (changes on nearly every sample, so it "
            f"carries no event information): {', '.join(flooding)}"
        )
    if trigger is None and not _is_running(changes[0].get("value"), run_state_tag):
        # Actionable rather than merely honest: the operator should widen the
        # window. Left unsaid, an unlabelled timeline reads as "the line was fine
        # until it recovered", which is the wrong end of the incident.
        notes.append(
            "this window opened with the asset already stopped — the stoppage began "
            "BEFORE it, so no trigger is in view; widen the window to find it"
        )
    return {
        "window": dict(window or {}),
        "segmented": True,
        "scope": "cross_asset" if downstream else "single_asset",
        "entries": entries,
        "note": " · ".join(
            [
                *notes,
                (
                    f"propagation follows {len(downstream)} declared relation(s)"
                    if downstream
                    else "single-asset timeline: no line relations are declared, so no change "
                    "on another asset is called propagation (`iaiops relations declare`)"
                ),
            ]
        ),
    }


def _event_tags(rows: list[dict[str, Any]], keep: str) -> tuple[set[str], list[str]]:
    """Which tags carry events, and which were excluded for changing constantly.

    ``keep`` (the declared run-state ref) is never excluded: even a chattering
    run-state is the subject of the investigation, and dropping it would remove
    the trigger itself.
    """
    totals: dict[str, int] = {}
    changes: dict[str, int] = {}
    last: dict[str, Any] = {}
    for row in rows:
        tag = str(row.get("tag", ""))
        value = num(row.get("value"))
        totals[tag] = totals.get(tag, 0) + 1
        if tag not in last or last[tag] != value:
            changes[tag] = changes.get(tag, 0) + 1
        last[tag] = value
    kept, dropped = set(), []
    for tag, total in totals.items():
        if (
            tag == keep
            or total < MIN_SAMPLES_TO_JUDGE
            or changes.get(tag, 0) / total <= CHATTER_SHARE
        ):
            kept.add(tag)
        else:
            dropped.append(tag)
    return kept, sorted(dropped)


def _changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per observed value CHANGE, per (asset, tag), in time order.

    The first sample of each series counts as a change: it is the first thing
    anybody observed, and dropping it would hide a window that opened already
    stopped.
    """
    ordered = sorted(
        (r for r in rows or () if parse_ts(r.get("ts")) is not None),
        key=lambda r: (parse_ts(r.get("ts")), str(r.get("asset", "")), str(r.get("tag", ""))),
    )
    last: dict[tuple[str, str], Any] = {}
    out: list[dict[str, Any]] = []
    truncated = False
    for row in ordered:
        key = (str(row.get("asset", "")), str(row.get("tag", "")))
        value = num(row.get("value"))
        if key in last and last[key] == value:
            continue
        last[key] = value
        out.append(row)
        if len(out) >= MAX_ENTRIES:
            truncated = True
            break
    if truncated and out:
        out[-1] = {**out[-1], _TRUNCATED: True}
    return out


def _is_running(value: Any, run_state_tag: dict[str, Any]) -> bool:
    """Running is what the CONFIG says it is — never "non-zero" (that would count
    idle and fault as production)."""
    running = [num(v) for v in (run_state_tag.get("running_when") or ())]
    return num(value) in running


def _first_stop(
    changes: list[dict[str, Any]], run_state_tag: dict[str, Any], primary: str
) -> dict[str, Any] | None:
    """The primary asset's first transition OUT of running.

    Out of running, not "the earliest change": a window that opens already
    stopped has no transition in it, and calling its first sample the trigger
    would invent an event nobody saw.
    """
    ref = str(run_state_tag.get("ref", ""))
    series = [c for c in changes if str(c.get("tag", "")) == ref and _same(c, primary)]
    for previous, current in zip(series, series[1:], strict=False):
        if _is_running(previous.get("value"), run_state_tag) and not _is_running(
            current.get("value"), run_state_tag
        ):
            return current
    return None


def _first_recovery(
    changes: list[dict[str, Any]],
    run_state_tag: dict[str, Any],
    primary: str,
    trigger: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if trigger is None:
        return None
    ref = str(run_state_tag.get("ref", ""))
    onset = parse_ts(trigger.get("ts"))
    for change in changes:
        if str(change.get("tag", "")) != ref or not _same(change, primary):
            continue
        at = parse_ts(change.get("ts"))
        if at is not None and at > onset and _is_running(change.get("value"), run_state_tag):
            return change
    return None


def _segment(
    change: dict[str, Any],
    trigger: dict[str, Any] | None,
    recovery: dict[str, Any] | None,
    primary: str,
    downstream: tuple[str, ...],
) -> str:
    if trigger is not None and change is trigger:
        return TRIGGER
    if recovery is not None and change is recovery:
        return RECOVERY
    asset = str(change.get("asset", ""))
    if asset and asset != primary and asset in downstream:
        # A declared edge is necessary but not sufficient: an effect cannot
        # precede its cause, so a downstream change before the trigger is not
        # propagation. Without this check a declared relation would launder any
        # co-occurrence into a causal claim.
        at, onset = parse_ts(change.get("ts")), parse_ts((trigger or {}).get("ts"))
        if onset is not None and at is not None and at > onset:
            return PROPAGATION
        return ""
    if trigger is None:
        return ""
    # A symptom is something the incident CAUSED, so it cannot precede the
    # trigger. The window's first observation is usually the line running
    # normally; labelling that a symptom would make the incident look like it
    # started before it did.
    at, onset = parse_ts(change.get("ts")), parse_ts(trigger.get("ts"))
    if at is None or onset is None or at <= onset:
        return ""
    return SYMPTOM


def _same(change: dict[str, Any], primary: str) -> bool:
    """A row with no asset label belongs to the investigation's own asset."""
    asset = str(change.get("asset", ""))
    return not asset or not primary or asset == primary


def _entry(change: dict[str, Any], segment: str) -> dict[str, Any]:
    return {
        "at": s(str(change.get("ts", "")), 40),
        "asset": s(str(change.get("asset", "")), 96),
        "tag": s(str(change.get("tag", "")), 96),
        "value": change.get("value"),
        "segment": segment,
        "evidence_id": s(str(change.get("id", "")), 160),
    }
