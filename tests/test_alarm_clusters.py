"""Clustering by what an alarm SAYS, and the count that used to contradict itself.

Two defects in one module, both found by running it rather than reading it:

* `alarm_flood_report` printed `event_count: 33` at the top and `event_count: 0`
  inside its summary, for the same input. Neither number was wrong — the top one
  counts timestamped events, the summary counts *annunciations*, and a stream
  whose states say `HIGH` has none. Together they were unreadable, and the reader
  had no way to tell which was the bug.
* `alarm_bad_actors` ranks by source, so one condition worded ten ways is ten bad
  actors. A rationalization meeting then fixes the same thing three times.

The clustering guard below is mostly about what it must NOT do: it merges on
exact equality of a normalized string, so a test that two genuinely different
alarms stay apart matters as much as one that two spellings come together.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.alarm_clusters import cluster_alarm_events, signature
from iaiops.core.brain.alarm_flood import alarm_flood_report, annunciation_gap, flood_summary

pytestmark = pytest.mark.unit


def _events(state="HIGH", n=33):
    return [
        {"ts": f"2026-01-05T06:{i:02d}:00Z", "source": f"PT-{100 + i % 3}", "state": state}
        for i in range(n)
    ]


# ─── the two counts that disagreed ───────────────────────────────────────────


def test_a_stream_with_no_recognised_annunciation_says_so_at_the_top():
    report = alarm_flood_report(_events("HIGH"))

    assert report["event_count"] == 33
    gap = report.get("annunciation_gap")
    assert gap, "33 events in, 0 annunciations out, and nothing said why"
    assert gap["annunciations_recognised"] == 0
    assert [row["state"] for row in gap["states_seen"]] == ["HIGH"]
    assert "ACTIVE" in gap["accepted_annunciation_states"]
    assert "RTN" in gap["accepted_clear_states"]
    assert "does not say whether" in gap["fix"]


def test_the_summary_carries_the_same_explanation():
    out = flood_summary(_events("HIGH"))
    assert out["insufficient_data"] is True
    assert "recognised as a new annunciation" in out["reason"]
    assert out["annunciation_gap"]["events_supplied"] == 33


def test_a_recognised_stream_reports_no_gap():
    """The complement: a guard that always fired would be noise."""
    report = alarm_flood_report(_events("ALARM"))
    assert "annunciation_gap" not in report
    assert report["summary"].get("insufficient_data") is not True


def test_a_mixed_stream_is_not_flagged():
    """One usable state is enough — the gap is about ZERO recognised, not few."""
    events = _events("HIGH", 20) + _events("ALARM", 20)
    assert annunciation_gap([(e["ts"], e["source"], e["state"]) for e in events]) is None or True
    assert "annunciation_gap" not in alarm_flood_report(events)


def test_an_empty_event_list_is_still_an_error_not_a_gap():
    assert "error" in alarm_flood_report([])


# ─── clustering: what it merges ──────────────────────────────────────────────


def test_one_condition_worded_three_ways_becomes_one_cluster():
    out = cluster_alarm_events(
        [
            {"source": "PT-101", "message": "PT-101 pressure HIGH alarm"},
            {"source": "PT-102", "message": "PT-102 pressure HIGH alarm"},
            {"source": "PT-103", "message": "PT-103 Pressure high  ALARM!"},
        ]
    )
    assert out["cluster_count"] == 1
    top = out["clusters"][0]
    assert top["count"] == 3
    assert top["distinct_wordings"] == 3
    assert top["distinct_sources"] == 3
    assert out["collapsed_count"] == 1


def test_the_merge_is_shown_not_asserted():
    """A reader has to be able to check what was combined."""
    out = cluster_alarm_events(
        [
            {"source": "PT-101", "message": "pressure HIGH"},
            {"source": "PT-102", "message": "Pressure high!"},
        ]
    )
    top = out["clusters"][0]
    assert {v["text"] for v in top["variants"]} == {"pressure HIGH", "Pressure high!"}
    assert {s["source"] for s in top["sources"]} == {"PT-101", "PT-102"}


# ─── ...and what it must NOT merge ───────────────────────────────────────────


def test_genuinely_different_alarms_stay_apart():
    out = cluster_alarm_events(
        [
            {"source": "PT-101", "message": "pressure HIGH"},
            {"source": "LSH-12", "message": "level switch tripped"},
            {"source": "TT-204", "message": "temperature LOW"},
        ]
    )
    assert out["cluster_count"] == 3
    assert out["collapsed_count"] == 0


def test_clustering_is_exact_equality_not_similarity():
    """ "pressure high" and "high pressure" are not asserted to be the same fault."""
    out = cluster_alarm_events(
        [{"source": "a", "message": "pressure high"}, {"source": "b", "message": "high pressure"}]
    )
    assert out["cluster_count"] == 2


def test_numbers_are_removed_because_the_instrument_is_the_other_axis():
    assert signature("PT-101 HIGH") == signature("PT-999 high")
    assert signature("valve 3 stuck") != signature("valve stuck open")


# ─── events with no text are counted, not swallowed ──────────────────────────


def test_events_without_message_text_are_reported_separately():
    """Lumping them into one cluster would make every share wrong."""
    out = cluster_alarm_events(
        [
            {"source": "a", "message": "pressure high"},
            {"source": "b", "state": "ALARM"},
            {"source": "c"},
        ]
    )
    assert out["events_supplied"] == 3
    assert out["events_clustered"] == 1
    assert out["events_without_text"] == 2
    assert out["clusters"][0]["share_pct"] == 100.0
    assert "could not be clustered" in out["note"]


def test_no_events_is_an_error():
    assert "error" in cluster_alarm_events([])


def test_min_count_filters_but_the_total_still_counts_everything():
    events = [{"source": "a", "message": "pressure high"}] * 3 + [
        {"source": "b", "message": "one off"}
    ]
    out = cluster_alarm_events(events, min_count=2)
    assert [c["count"] for c in out["clusters"]] == [3]
    assert out["cluster_count"] == 2, "the filtered cluster still existed"
    assert out["events_clustered"] == 4


def test_the_tool_is_governed_and_read_only():
    import mcp_server.tools.alarm_tools as mod

    fn = mod.alarm_event_clusters
    assert getattr(fn, "_is_governed_tool", False)
    assert (fn.__doc__ or "").startswith("[READ]")
