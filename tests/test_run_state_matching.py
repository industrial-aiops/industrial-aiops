"""A status word must match whether YAML quoted it or the wire delivered a float.

Found 2026-08-24 by measuring a real Modbus line. The config said
`running_when: "2"` — YAML's natural spelling for a status word — and the
register arrived as the float `2.0`. `is_running` saw one string, compared as
text, and `"2" != "2.0"`, so a line that ran for 88% of the samples measured as

    Availability — line1 · tag 0
      0.00% over 97.54% coverage

**Note the direction.** Zero availability turns a healthy line into four minutes
of unexplained downtime — exactly the loss a vendor then offers to fix. Sixth of
its kind in this codebase, and the docstring on `is_running` had been warning
about precisely this failure while producing it through its own string branch.

Two guards, because the comparison fix only closes the cases we thought of:

* same number matches however it is spelled;
* a run-state tag that was sampled and NEVER matched refuses to report a figure,
  and prints the declared value beside the observed ones.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain.oee_measure import measure_availability
from iaiops.core.runtime.config import MonitorTag, TagRole

pytestmark = pytest.mark.unit


def _tag(running_when: object) -> MonitorTag:
    return MonitorTag(ref="0", role=TagRole.RUN_STATE, running_when=running_when)


class TestTheSameNumberMatchesHoweverItIsSpelled:
    @pytest.mark.parametrize(
        ("declared", "observed"),
        [
            ("2", 2.0),  # the case that measured a running line at 0%
            ("2", 2),
            (2, 2.0),
            (2, "2.0"),
            (2.0, "2"),
            ("02", 2),  # a leading zero is spelling, not meaning
            (" 2 ", 2.0),  # YAML whitespace is spelling too
            (1, True),  # a Modbus coil reads back as a bool
            ("1", True),
        ],
    )
    def test_it_matches(self, declared, observed):
        assert _tag([declared]).is_running(observed) is True

    @pytest.mark.parametrize(
        ("declared", "observed"),
        [
            ("2", 3.0),
            ("2", 0.0),  # the status-word trap: stopped must never read as running
            (2, 1),  # nor idle
            (2, 3),  # nor fault
            ("RUNNING", 2.0),
            ("RUNNING", "STOPPED"),
            (1, False),
        ],
    )
    def test_it_does_not_match(self, declared, observed):
        assert _tag([declared]).is_running(observed) is False

    @pytest.mark.parametrize("spelling", ["RUNNING", "running", "Running", " running "])
    def test_genuine_words_still_compare_case_insensitively(self, spelling):
        assert _tag(["Running"]).is_running(spelling) is True

    def test_a_run_state_tag_cannot_be_declared_without_running_when(self):
        """The trap the whole design exists to close, guarded at construction."""
        with pytest.raises(ValueError) as excinfo:
            _tag([])
        assert "running_when" in str(excinfo.value)

    def test_an_empty_declaration_still_matches_nothing(self):
        """And guarded again here, so relaxing the constructor later cannot
        silently reopen it — 'anything truthy' is never the fallback."""
        bare = MonitorTag(ref="0")
        for observed in (2.0, 1, True, "RUNNING", "anything"):
            assert bare.is_running(observed) is False

    def test_a_non_numeric_value_does_not_crash_the_numeric_path(self):
        assert _tag(["2"]).is_running("bad quality") is False
        assert _tag([2]).is_running(None) is False


def _series(values: list[float], step_s: float = 0.5) -> list[dict]:
    start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    return [
        {"ts": (start + timedelta(seconds=i * step_s)).isoformat(), "value": v}
        for i, v in enumerate(values)
    ]


class TestNothingMatchingIsRefusedNotReportedAsZero:
    def test_a_never_matching_tag_reports_no_figure(self):
        result = measure_availability(_series([2.0] * 40), _tag(["RUNNING"]))
        assert result["status"] == "no_running_state_matched"
        assert result["availability"] is None

    def test_it_prints_the_two_values_to_compare(self):
        """Without both, the operator has to go and query the store — the step
        nobody takes, which is why the wrong figure survives."""
        result = measure_availability(_series([2.0] * 30 + [0.0] * 10), _tag(["RUNNING"]))
        assert result["running_when"] == ["RUNNING"]
        assert set(result["observed_values"]) == {"2.0", "0.0"}

    def test_a_genuinely_stopped_line_is_still_reported_as_stopped(self):
        """The refusal must not swallow the real case. A line that was declared
        correctly and simply did not run has a matching value in the series —
        here it ran once — and gets a figure, low as it is."""
        result = measure_availability(_series([0.0] * 39 + [2.0]), _tag(["2"]))
        assert result["status"] == "ok"
        assert result["availability"] == 0.0

    def test_a_running_line_reports_the_figure_the_samples_support(self):
        """The regression the fix exists for: 88% of samples running must not
        measure as zero."""
        result = measure_availability(_series([2.0] * 88 + [0.0] * 12), _tag(["2"]))
        assert result["status"] == "ok"
        assert result["availability"] == pytest.approx(0.88, abs=0.02)

    def test_too_few_samples_is_still_its_own_answer(self):
        """'Nothing matched' must not shadow 'you have not collected yet'."""
        result = measure_availability(_series([2.0] * 3), _tag(["RUNNING"]))
        assert result["status"] == "insufficient_data"

    def test_the_observed_list_is_bounded(self):
        """A tag mis-declared as run_state may be an analog reading; echoing a
        thousand distinct values back is not a teaching message."""
        from iaiops.core.brain.oee_measure import MAX_OBSERVED_VALUES

        result = measure_availability(_series([float(i) for i in range(60)]), _tag(["RUNNING"]))
        assert len(result["observed_values"]) == MAX_OBSERVED_VALUES
