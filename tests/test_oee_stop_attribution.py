"""Which stoppages a person explained, and which nobody did.

The run-state tag decides THAT the line stopped and for how long — automatically,
from the declared ``running_when``. It does not decide WHY: a status word is not
given a vocabulary of reasons (D16), and the loss ladder already refuses to split
breakdown from setup on its own. The only reasons this product holds are the ones
a person gave through ``iaiops case confirm``.

Before this, nothing joined the two. A measured window reported N stoppages and a
case store held M answers, and a reader could not tell how many of the N had any
reason at all. That gap is exactly where a vendor's "classified downtime" number
flatters: count a case that merely carries audit-trail actions as explained, or
quietly drop the stoppages that were never examined, and the explained share goes
up without anyone having explained anything.

So every stoppage lands in exactly one class, the classes sum to the stoppages
measured, and the ones beyond the examined list are counted as NOT examined
rather than folded into any class.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.oee_attribution import (
    AWAITING_PERSON,
    NO_CASE,
    ONSET_BEFORE_WINDOW,
    PERSON_CONFIRMED,
    PERSON_DISMISSED,
    attribute_stops,
)
from iaiops.core.brain.oee_measure import measure_availability
from iaiops.core.knowledge.case_store import (
    case_id,
    confirm_case,
    dismiss_case,
    list_cases,
    open_case,
)
from iaiops.core.runtime.config import MonitorTag, TagRole

pytestmark = pytest.mark.unit

RUN = MonitorTag(ref="40001", role=TagRole.RUN_STATE, running_when=(2,))
SITE = "plant-a"
EP = "line1"


def ts(second: int) -> str:
    h, rem = divmod(second, 3600)
    return f"2026-08-01T{h:02d}:{rem // 60:02d}:{rem % 60:02d}+00:00"


def series(states: list[tuple[int, int, int]]) -> list[dict]:
    """``(start, end, state)`` spans at 1s cadence → store rows."""
    return [{"ts": ts(s), "value": v} for a, b, v in states for s in range(a, b)]


#: Three stops: 600s at t=1000, 400s at t=3000, 60s (minor) at t=5000.
THREE_STOPS = series(
    [
        (0, 1000, 2),
        (1000, 1600, 3),
        (1600, 3000, 2),
        (3000, 3400, 0),
        (3400, 5000, 2),
        (5000, 5060, 1),
        (5060, 6000, 2),
    ]
)


def measured(rows=THREE_STOPS, **kw):
    out = measure_availability(rows, RUN, **kw)
    assert out["status"] == "ok"
    return out


def onsets(m):
    return {w["duration_s"]: w["onset"] for w in m["stop_windows"]}


class TestEveryStopLandsInExactlyOneClass:
    def test_with_no_cases_every_stop_is_unexplained(self, tmp_path):
        m = measured()
        out = attribute_stops(m, EP, cases=[])
        assert out["status"] == "ok"
        assert out["stops"] == 3
        assert out["classes"][NO_CASE]["count"] == 3
        assert out["classes"][PERSON_CONFIRMED]["count"] == 0
        assert out["classes"][NO_CASE]["duration_s"] == pytest.approx(m["stopped_s"], abs=1)

    def test_a_confirmed_case_is_a_person_given_reason(self, tmp_path):
        m = measured()
        first = onsets(m)[600.0]
        opened = open_case(SITE, EP, first, base_dir=tmp_path)
        confirm_case(SITE, opened.incident_id, "mechanical_fault", by="li", base_dir=tmp_path)
        out = attribute_stops(m, EP, cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][PERSON_CONFIRMED]["count"] == 1
        assert out["classes"][PERSON_CONFIRMED]["duration_s"] == pytest.approx(600, abs=1)
        row = next(w for w in out["windows"] if w["attribution"] == PERSON_CONFIRMED)
        assert row["cause"] == "mechanical_fault"
        assert row["answered_by"] == "li"
        assert row["answered_at"]

    def test_a_dismissal_is_a_person_saying_it_was_not_an_incident(self, tmp_path):
        m = measured()
        opened = open_case(SITE, EP, onsets(m)[400.0], base_dir=tmp_path)
        dismiss_case(SITE, opened.incident_id, by="wang", base_dir=tmp_path)
        out = attribute_stops(m, EP, cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][PERSON_DISMISSED]["count"] == 1
        row = next(w for w in out["windows"] if w["attribution"] == PERSON_DISMISSED)
        assert row["cause"] == ""
        assert row["answered_by"] == "wang"

    def test_the_classes_sum_to_the_stops_measured(self, tmp_path):
        m = measured()
        o = onsets(m)
        a = open_case(SITE, EP, o[600.0], base_dir=tmp_path)
        confirm_case(SITE, a.incident_id, "mechanical_fault", by="li", base_dir=tmp_path)
        open_case(SITE, EP, o[400.0], base_dir=tmp_path)
        out = attribute_stops(m, EP, cases=list_cases(SITE, base_dir=tmp_path))
        total = sum(c["count"] for c in out["classes"].values()) + out["not_examined"]
        assert total == out["stops"] == m["stops"]
        seconds = sum(c["duration_s"] for c in out["classes"].values()) + out["not_examined_s"]
        assert seconds == pytest.approx(m["stopped_s"], abs=1)


class TestNothingCountsAsExplainedThatNobodyExplained:
    """The flattering direction is UP: more explained than was."""

    def test_audit_trail_actions_are_not_a_reason(self, tmp_path):
        """`case open` attaches what someone DID afterwards and marks the capture
        'inferred'. That is a recorded fact, not a cause — counting it as
        explained would credit the trail with a person's judgement."""
        m = measured()
        audit = [
            {
                "ts": ts(1100),
                "tool": "modbus_write_register",
                "status": "ok",
                "risk_level": "high",
                "user": "zhang",
            }
        ]
        opened = open_case(SITE, EP, onsets(m)[600.0], audit_rows=audit, base_dir=tmp_path)
        assert opened.capture == "inferred"  # the trap is real: the case HAS a capture
        out = attribute_stops(m, EP, cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][PERSON_CONFIRMED]["count"] == 0
        assert out["classes"][AWAITING_PERSON]["count"] == 1

    def test_a_case_for_another_endpoint_explains_nothing_here(self, tmp_path):
        m = measured()
        other = open_case(SITE, "line2", onsets(m)[600.0], base_dir=tmp_path)
        confirm_case(SITE, other.incident_id, "mechanical_fault", by="li", base_dir=tmp_path)
        out = attribute_stops(m, EP, cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][PERSON_CONFIRMED]["count"] == 0
        assert out["classes"][NO_CASE]["count"] == 3

    def test_no_reason_is_ever_assigned_from_the_signal(self):
        out = attribute_stops(measured(), EP, cases=[])
        assert out["reasons_from_signal"] == 0
        assert "run_state" in out["detected_by"]

    def test_a_refused_measurement_attributes_nothing(self):
        thin = measure_availability(series([(0, 5, 2)]), RUN)
        assert thin["status"] != "ok"
        out = attribute_stops(thin, EP, cases=[])
        assert out["status"] == "no_measurement"
        assert "classes" not in out


class TestStopsBeyondTheListAreNotExamined:
    def test_a_capped_list_reports_the_rest_as_not_examined(self, tmp_path):
        m = measured(max_stop_windows=1)
        assert m["stops"] == 3 and len(m["stop_windows"]) == 1
        out = attribute_stops(m, EP, cases=[])
        assert out["is_truncated"] is True
        assert out["examined"] == 1
        assert out["not_examined"] == 2
        assert out["classes"][NO_CASE]["count"] == 1  # not 3: unexamined is not "no case"
        assert out["not_examined_s"] == pytest.approx(460, abs=2)

    def test_an_uncapped_list_examines_every_stop(self):
        m = measured(max_stop_windows=None)
        out = attribute_stops(m, EP, cases=[])
        assert out["is_truncated"] is False
        assert out["not_examined"] == 0


class TestWhoAnsweredIsRecorded:
    def test_confirm_records_who_and_when_in_fields_not_only_the_note(self, tmp_path):
        opened = open_case(SITE, EP, ts(1000), base_dir=tmp_path)
        done = confirm_case(
            SITE, opened.incident_id, "mechanical_fault", by=" li ", base_dir=tmp_path
        )
        assert done.answered_by == "li"
        assert done.answered_at.startswith("20")
        again = list_cases(SITE, base_dir=tmp_path)[0]
        assert (again.answered_by, again.answered_at) == (done.answered_by, done.answered_at)

    def test_an_older_case_without_the_fields_reads_back_as_unknown(self, tmp_path):
        from iaiops.core.knowledge.cases import Case

        old = Case(incident_id="x", when=ts(0), label="mechanical_fault", capture="override")
        assert old.answered_by == "" and old.answered_at == ""
        assert "answered_by" not in old.as_fact().value

    def test_case_id_is_the_join_key(self):
        assert case_id(EP, ts(1000)) == open_case.__globals__["_case_id"](EP, ts(1000))


class TestBlindWindowsAreNeverTruncated:
    """Production counting skips increments that span a blind window. A capped
    list silently lets the 51st outage's parts back in — Performance goes up in
    proportion to how blind a long window was."""

    def test_all_blind_windows_are_published(self):
        spans = []
        t = 0
        for _ in range(60):
            spans.append((t, t + 20, 2))
            t += 40  # 20s hole after each 20s burst → a blind window each time
        m = measure_availability(series(spans), RUN)
        assert len(m["blind_windows"]) == 59
        assert m["blind_windows_total"] == 59

    def test_the_stop_list_cap_does_not_touch_blind_windows(self):
        spans = [(i * 40, i * 40 + 20, 2) for i in range(60)]
        m = measure_availability(series(spans), RUN, max_stop_windows=1)
        assert len(m["blind_windows"]) == 59


class TestTheJoinIsExact:
    """Review finding: the case id drops sub-second precision and sanitizes the
    endpoint, so an id-only join credited one confirmation to several stops."""

    def _jittered(self):
        # 0.3s cadence; a 0.3s micro-stop at 13:00:00.0, a long stop at 13:00:00.6.
        base = 13 * 3600
        rows = []
        t = 0.0
        while t < 2000:
            if 30.0 <= t < 30.3:
                v = 0
            elif 30.6 <= t < 630.6:
                v = 0
            else:
                v = 2
            sec = base + t
            h, rem = divmod(int(sec), 3600)
            frac = f"{sec - int(sec):.1f}"[1:]
            rows.append(
                {"ts": f"2026-08-01T{h:02d}:{rem // 60:02d}:{rem % 60:02d}{frac}+00:00", "value": v}
            )
            t = round(t + 0.3, 1)
        return rows

    def test_two_stops_in_one_second_are_not_both_credited(self, tmp_path):
        m = measured(self._jittered(), max_stop_windows=None)
        assert m["stops"] == 2
        long = max(m["stop_windows"], key=lambda w: w["duration_s"])
        short = min(m["stop_windows"], key=lambda w: w["duration_s"])
        assert case_id(EP, long["onset"]) == case_id(EP, short["onset"])  # the trap
        opened = open_case(SITE, EP, long["onset"], base_dir=tmp_path)
        confirm_case(SITE, opened.incident_id, "mechanical_fault", by="li", base_dir=tmp_path)
        out = attribute_stops(m, EP, cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][PERSON_CONFIRMED]["count"] == 1
        assert out["classes"][NO_CASE]["count"] == 1

    def test_an_endpoint_that_sanitizes_to_the_same_id_explains_nothing_here(self, tmp_path):
        m = measured()
        onset = onsets(m)[600.0]
        assert case_id("line_1", onset) == case_id("line-1", onset)  # the trap
        other = open_case(SITE, "line_1", onset, base_dir=tmp_path)
        confirm_case(SITE, other.incident_id, "mechanical_fault", by="li", base_dir=tmp_path)
        out = attribute_stops(m, "line-1", cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][PERSON_CONFIRMED]["count"] == 0


class TestAStopAlreadyInProgressAtTheWindowStart:
    """Review finding: its onset in a narrower window is the first sample, not the
    onset its case was opened under — calling it "never put to a person" is a
    false statement about people."""

    def test_it_is_its_own_class_not_no_case(self, tmp_path):
        rows = series([(0, 100, 2), (100, 900, 0), (900, 2000, 2)])
        whole = measured(rows)
        opened = open_case(SITE, EP, whole["stop_windows"][0]["onset"], base_dir=tmp_path)
        confirm_case(SITE, opened.incident_id, "mechanical_fault", by="li", base_dir=tmp_path)
        narrow = measured(rows, window=(ts(500), ts(1999)))
        assert narrow["stop_windows"][0]["open_at_start"] is True
        out = attribute_stops(narrow, EP, cases=list_cases(SITE, base_dir=tmp_path))
        assert out["classes"][NO_CASE]["count"] == 0
        assert out["classes"][ONSET_BEFORE_WINDOW]["count"] == 1

    def test_a_stop_that_starts_inside_is_not_flagged(self):
        assert all(not w["open_at_start"] for w in measured()["stop_windows"])


def test_the_cases_read_are_counted_so_a_wrong_site_is_visible():
    out = attribute_stops(measured(), EP, cases=[])
    assert out["cases_read"] == 0
