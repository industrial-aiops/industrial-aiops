"""Trigger · Symptom · Propagation · Recovery — a re-ordering, not a story.

HLD §13.7. Of the eight steps this is the one that looks most like intelligence
and is easiest to turn into fiction, so it is fenced by three rules:

1. **Every line cites an evidence id.** The timeline produces no new facts; it
   re-orders ones already in the store, and each entry says which sample it came
   from so a reader can go back to it.
2. **Propagation edges come only from declared relations** (D25). On a line,
   everything downstream of a stoppage correlates with it — inferring
   propagation from time would manufacture a causal chain out of a guarantee.
3. **Degradation is explicit.** With no declared relations, it produces a
   SINGLE-ASSET timeline and says so. A four-segment timeline that silently
   dropped propagation would read as "nothing propagated".

And a fourth, which is what keeps the labels honest: the four segments require a
**declared run-state tag**. Calling the first change "Trigger" without knowing
which value means running is a guess dressed as a finding — so without the role,
this returns a plain ordered change list and refuses the labels.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.timeline import build_timeline

pytestmark = pytest.mark.unit

WINDOW = {"start": "2026-08-26T10:00:00Z", "end": "2026-08-26T10:10:00Z", "asset": "press"}


def sample(tag: str, value: float, at: str, asset: str = "press") -> dict:
    return {"tag": tag, "value": value, "ts": at, "asset": asset, "id": f"{asset}/{tag}@{at}"}


#: A press that runs, faults, and comes back. `2` is running here.
RUN_STOP_RUN = [
    sample("state", 2.0, "2026-08-26T10:00:00Z"),
    sample("state", 2.0, "2026-08-26T10:01:00Z"),
    sample("state", 3.0, "2026-08-26T10:02:00Z"),  # fault — the trigger
    sample("state", 3.0, "2026-08-26T10:03:00Z"),
    sample("state", 2.0, "2026-08-26T10:05:00Z"),  # back — the recovery
]


class TestTheFourSegmentsNeedDeclaredSemantics:
    def test_without_a_run_state_role_it_refuses_the_labels(self):
        """ "The first change is the Trigger" is only true if you know which value
        means running. Without that it is a guess dressed as a finding."""
        out = build_timeline(WINDOW, RUN_STOP_RUN, run_state_tag=None)
        assert out["segmented"] is False
        assert "run_state" in out["note"]

    def test_it_still_returns_the_changes_in_order(self):
        """Refusing the labels is not refusing the step. An ordered change list
        is useful on its own and claims nothing it cannot support."""
        out = build_timeline(WINDOW, RUN_STOP_RUN, run_state_tag=None)
        assert [e["at"] for e in out["entries"]] == [
            "2026-08-26T10:00:00Z",
            "2026-08-26T10:02:00Z",
            "2026-08-26T10:05:00Z",
        ]

    def test_with_the_role_it_segments(self):
        out = build_timeline(
            WINDOW, RUN_STOP_RUN, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert out["segmented"] is True
        labelled = [e["segment"] for e in out["entries"] if e["segment"]]
        assert labelled == ["trigger", "recovery"]

    def test_an_observation_before_the_trigger_is_not_a_symptom(self):
        """A symptom is something the incident CAUSED, so it cannot precede the
        trigger. The window's first observation is the line running normally;
        labelling it a symptom makes the incident look like it started earlier
        than it did — and that is the direction that inflates downtime."""
        out = build_timeline(
            WINDOW, RUN_STOP_RUN, run_state_tag={"ref": "state", "running_when": [2]}
        )
        first = out["entries"][0]
        assert first["at"] == "2026-08-26T10:00:00Z"
        assert first["segment"] == "", first

    def test_the_trigger_is_the_transition_out_of_running(self):
        out = build_timeline(
            WINDOW, RUN_STOP_RUN, run_state_tag={"ref": "state", "running_when": [2]}
        )
        trigger = next(e for e in out["entries"] if e["segment"] == "trigger")
        assert trigger["at"] == "2026-08-26T10:02:00Z"

    def test_the_recovery_is_the_transition_back(self):
        out = build_timeline(
            WINDOW, RUN_STOP_RUN, run_state_tag={"ref": "state", "running_when": [2]}
        )
        recovery = next(e for e in out["entries"] if e["segment"] == "recovery")
        assert recovery["at"] == "2026-08-26T10:05:00Z"

    def test_a_line_that_never_stopped_has_no_trigger(self):
        """The complement: a segmenter that always found a trigger would find one
        in a window where nothing happened."""
        steady = [sample("state", 2.0, f"2026-08-26T10:0{n}:00Z") for n in range(5)]
        out = build_timeline(WINDOW, steady, run_state_tag={"ref": "state", "running_when": [2]})
        assert not any(e["segment"] == "trigger" for e in out["entries"])


class TestAWindowThatOpensAlreadyStopped:
    """The case that separates "first transition out of running" from "first
    change" — and the one my first fixture could not see.

    Replacing the transition test with `if True` kept all 17 tests green, because
    in a run→stop→run window both rules pick the same row. Here they do not: with
    the stoppage already underway, the only transition in view is the RECOVERY,
    and the loose rule labels it the trigger — an event that did not happen,
    placed at the moment the line came back.
    """

    OPENS_STOPPED = [
        sample("state", 3.0, "2026-08-26T10:00:00Z"),  # already down when we looked
        sample("state", 3.0, "2026-08-26T10:02:00Z"),
        sample("state", 2.0, "2026-08-26T10:05:00Z"),  # comes back
    ]

    def test_there_is_no_trigger_in_view(self):
        out = build_timeline(
            WINDOW, self.OPENS_STOPPED, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert not any(e["segment"] == "trigger" for e in out["entries"]), out["entries"]

    def test_the_recovery_is_not_mislabelled_as_the_trigger(self):
        """The specific lie the loose rule tells."""
        out = build_timeline(
            WINDOW, self.OPENS_STOPPED, run_state_tag={"ref": "state", "running_when": [2]}
        )
        at_recovery = [e for e in out["entries"] if e["at"] == "2026-08-26T10:05:00Z"]
        assert at_recovery and at_recovery[0]["segment"] != "trigger"

    def test_it_says_the_stoppage_began_before_the_window(self):
        """Actionable: the operator should widen the window, not conclude the line
        was fine until 10:05."""
        out = build_timeline(
            WINDOW, self.OPENS_STOPPED, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert "before" in out["note"].lower(), out["note"]


class TestEveryLineCitesItsEvidence:
    def test_each_entry_carries_the_sample_it_came_from(self):
        out = build_timeline(WINDOW, RUN_STOP_RUN, run_state_tag=None)
        assert all(e["evidence_id"] for e in out["entries"])

    def test_the_id_is_the_one_the_store_gave_it(self):
        """Not a re-invented key. A citation nobody can follow back is decoration."""
        out = build_timeline(WINDOW, RUN_STOP_RUN, run_state_tag=None)
        assert out["entries"][0]["evidence_id"] == "press/state@2026-08-26T10:00:00Z"

    def test_it_invents_no_entries(self):
        """One entry per observed CHANGE, never more. Interpolating a value
        nobody sampled is exactly how a timeline becomes fiction."""
        out = build_timeline(WINDOW, RUN_STOP_RUN, run_state_tag=None)
        observed = {e["evidence_id"] for e in out["entries"]}
        assert observed <= {row["id"] for row in RUN_STOP_RUN}


class TestPropagationOnlyFollowsDeclaredRelations:
    OVEN_STOPS_TOO = [
        *RUN_STOP_RUN,
        sample("state", 3.0, "2026-08-26T10:02:30Z", asset="oven"),
    ]

    def test_without_relations_the_downstream_asset_is_not_called_propagation(self):
        """D25. The oven stopping thirty seconds after the press is exactly what a
        line does whatever the cause — calling it propagation on timing alone
        manufactures a causal chain out of a guarantee."""
        out = build_timeline(
            WINDOW,
            self.OVEN_STOPS_TOO,
            run_state_tag={"ref": "state", "running_when": [2]},
            downstream=(),
        )
        assert not any(e["segment"] == "propagation" for e in out["entries"])

    def test_with_a_declared_relation_it_is(self):
        out = build_timeline(
            WINDOW,
            self.OVEN_STOPS_TOO,
            run_state_tag={"ref": "state", "running_when": [2]},
            downstream=("oven",),
        )
        propagated = [e for e in out["entries"] if e["segment"] == "propagation"]
        assert [e["asset"] for e in propagated] == ["oven"]

    def test_an_undeclared_asset_stays_unattributed(self):
        """Declaring press→oven says nothing about a third machine."""
        rows = [*self.OVEN_STOPS_TOO, sample("state", 3.0, "2026-08-26T10:02:40Z", asset="packer")]
        out = build_timeline(
            WINDOW, rows, run_state_tag={"ref": "state", "running_when": [2]}, downstream=("oven",)
        )
        packer = [e for e in out["entries"] if e["asset"] == "packer"]
        assert packer and all(e["segment"] != "propagation" for e in packer)

    def test_a_downstream_change_before_the_trigger_is_not_propagation(self):
        """Time order still applies inside a declared relation: an effect cannot
        precede its cause. Without this, a declared edge would launder any
        co-occurrence into propagation."""
        rows = [
            *RUN_STOP_RUN,
            sample("state", 3.0, "2026-08-26T10:00:30Z", asset="oven"),  # BEFORE the press faulted
        ]
        out = build_timeline(
            WINDOW, rows, run_state_tag={"ref": "state", "running_when": [2]}, downstream=("oven",)
        )
        oven = [e for e in out["entries"] if e["asset"] == "oven"]
        assert oven and all(e["segment"] != "propagation" for e in oven)


class TestItSaysHowItDegraded:
    def test_with_no_relations_it_declares_itself_single_asset(self):
        out = build_timeline(
            WINDOW, RUN_STOP_RUN, run_state_tag={"ref": "state", "running_when": [2]}, downstream=()
        )
        assert out["scope"] == "single_asset"
        assert "relation" in out["note"].lower(), out["note"]

    def test_with_relations_it_says_so(self):
        out = build_timeline(
            WINDOW,
            RUN_STOP_RUN,
            run_state_tag={"ref": "state", "running_when": [2]},
            downstream=("oven",),
        )
        assert out["scope"] == "cross_asset"

    def test_an_empty_window_produces_no_timeline_and_says_why(self):
        out = build_timeline(WINDOW, [], run_state_tag=None)
        assert out["entries"] == []
        assert out["note"]


class TestACounterIsNotATimelineOfEvents:
    """Found by running it on the real cross-LAN collection.

    A production counter increments on essentially every sample, so treating
    "the value changed" as an event made every sample an event: 500 entries,
    hitting the cap, the incident buried under a counter ticking. A monotonic
    counter has no STATES — it carries no event information at all, and its
    presence pushed the real trigger and recovery off the end of the list.

    Excluded and NAMED, never silently dropped: an operator who declared that
    tag deserves to know why it is not on the timeline.
    """

    @pytest.fixture
    def state_and_counter(self):
        rows = []
        for i in range(40):
            at = f"2026-08-26T10:{i // 60:02d}:{i % 60:02d}Z"
            rows.append(sample("state", 3.0 if 10 <= i < 20 else 2.0, at))
            rows.append(sample("count", float(i), at))  # changes every single sample
        return rows

    def test_the_counter_does_not_flood_the_timeline(self, state_and_counter):
        out = build_timeline(
            WINDOW, state_and_counter, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert not any(e["tag"] == "count" for e in out["entries"]), out["entries"][:3]

    def test_the_state_transitions_survive(self, state_and_counter):
        """The complement — and the point. Dropping the counter must leave the
        incident visible, not blank the timeline."""
        out = build_timeline(
            WINDOW, state_and_counter, run_state_tag={"ref": "state", "running_when": [2]}
        )
        labelled = [e["segment"] for e in out["entries"] if e["segment"]]
        assert "trigger" in labelled and "recovery" in labelled

    def test_the_excluded_tag_is_named(self, state_and_counter):
        """Silently dropping a tag somebody declared is how a timeline starts
        lying by omission."""
        out = build_timeline(
            WINDOW, state_and_counter, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert "count" in out["note"], out["note"]

    def test_the_run_state_tag_is_never_excluded(self, state_and_counter):
        """Even a run-state that chatters is the subject of the investigation.
        Excluding it would remove the trigger itself."""
        chattering = [
            sample("state", float(2 + i % 2), f"2026-08-26T10:00:{i:02d}Z") for i in range(40)
        ]
        out = build_timeline(
            WINDOW, chattering, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert any(e["tag"] == "state" for e in out["entries"])


class TestTruncationIsNeverSilent:
    """A partial timeline that does not say so reads as a complete one — and the
    part it drops is the LATER part, which is where a recovery lives."""

    def test_it_says_when_the_cap_cut_the_window_short(self):
        from iaiops.core.brain.timeline import MAX_ENTRIES

        rows = [
            sample("s", float(i % 2), f"2026-08-26T10:00:00.{i:04d}Z")
            for i in range(MAX_ENTRIES + 50)
        ]
        out = build_timeline(WINDOW, rows, run_state_tag={"ref": "s", "running_when": [0]})
        assert len(out["entries"]) == MAX_ENTRIES
        assert "truncated" in out["note"].lower(), out["note"]

    def test_a_window_within_the_cap_says_nothing_about_truncation(self):
        """The complement: a warning that always fires is a warning nobody reads."""
        out = build_timeline(
            WINDOW, RUN_STOP_RUN, run_state_tag={"ref": "state", "running_when": [2]}
        )
        assert "truncated" not in out["note"].lower()
