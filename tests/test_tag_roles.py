"""Semantic roles on a tag — the unlock `readiness` has been naming.

`oee_compute` takes five plain numbers and `MonitorTag` carried only a ref, a
label and thresholds, so there was no way to say "this tag is the production
counter". OEE could therefore never be derived from a configured line, only
hand-fed.

The whole design turns on one refusal. `oee._is_running` treats any non-zero
NUMBER as running, which is correct for a boolean and dangerously wrong for the
status word most PLCs actually expose — `0=stopped 1=idle 2=running 3=fault
4=changeover` would count idle, fault AND changeover as productive time. That
inflates Availability, inflates OEE, and does so in the direction that flatters
whoever is selling the tool.

So declaring `role: run_state` REQUIRES saying which values mean running. It is
one extra line of config, and it removes the entire class of error. Which value
means running is process knowledge — exactly the thing D16 says we must never
guess.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.config import MonitorTag, TagRole, parse_tags

pytestmark = pytest.mark.unit


class TestRolesAreDeclaredNeverGuessed:
    def test_a_tag_has_no_role_by_default(self):
        """Silence means unknown, not "probably not important"."""
        assert MonitorTag(ref="40001").role == ""

    def test_a_declared_role_is_kept_verbatim(self):
        tag = MonitorTag(ref="40010", role=TagRole.TOTAL_COUNT)
        assert tag.role == "total_count"

    def test_an_unknown_role_is_refused_with_the_vocabulary(self):
        """A typo'd role must not silently become "no role" — that would turn a
        configured line back into an unconfigured one without saying so."""
        with pytest.raises(ValueError, match="(?i)role"):
            MonitorTag(ref="x", role="produciton_count")

    def test_the_error_names_what_is_allowed(self):
        with pytest.raises(ValueError) as excinfo:
            MonitorTag(ref="x", role="nonsense")
        assert "total_count" in str(excinfo.value)


class TestRunStateMustSayWhatRunningMeans:
    def test_run_state_without_running_when_is_refused(self):
        """The refusal that makes the feature safe. Defaulting to "non-zero" on
        a PLC status word counts idle and fault as production."""
        with pytest.raises(ValueError, match="(?i)running_when"):
            MonitorTag(ref="40001", role=TagRole.RUN_STATE)

    def test_the_refusal_explains_the_consequence_not_just_the_rule(self):
        with pytest.raises(ValueError) as excinfo:
            MonitorTag(ref="40001", role=TagRole.RUN_STATE)
        message = str(excinfo.value)
        assert "idle" in message.lower() or "fault" in message.lower()

    def test_an_explicit_value_set_is_accepted(self):
        tag = MonitorTag(ref="40001", role=TagRole.RUN_STATE, running_when=(2,))
        assert tag.running_when == (2,)

    def test_several_values_may_count_as_running(self):
        """A machine can be productive in more than one state."""
        tag = MonitorTag(ref="40001", role=TagRole.RUN_STATE, running_when=(2, 5))
        assert tag.is_running(5) is True
        assert tag.is_running(3) is False

    def test_a_boolean_line_is_expressed_the_same_way(self):
        tag = MonitorTag(ref="C1", role=TagRole.RUN_STATE, running_when=(True,))
        assert tag.is_running(True) is True
        assert tag.is_running(False) is False

    def test_string_states_compare_case_insensitively(self):
        tag = MonitorTag(ref="S", role=TagRole.RUN_STATE, running_when=("RUNNING",))
        assert tag.is_running("running") is True
        assert tag.is_running("FAULT") is False

    def test_the_status_word_trap_is_actually_closed(self):
        """The concrete case this feature exists for: with 0=stopped 1=idle
        2=running 3=fault, only 2 is production. The old non-zero default would
        have called three of those four states productive."""
        tag = MonitorTag(ref="40001", role=TagRole.RUN_STATE, running_when=(2,))
        assert [tag.is_running(v) for v in (0, 1, 2, 3)] == [False, False, True, False]

    def test_nothing_declared_matches_nothing(self):
        """Locks the rule at the METHOD too, not only in the constructor. If a
        later change relaxes the constructor, an implicit "anything truthy"
        fallback must not be waiting underneath it."""
        tag = MonitorTag(ref="40010", role=TagRole.TOTAL_COUNT)
        assert tag.is_running(1) is False
        assert tag.is_running(True) is False
        assert tag.is_running("RUNNING") is False

    def test_one_and_true_are_deliberately_equivalent(self):
        """A Modbus coil reads back as a bool while the config author naturally
        writes `running_when: [1]`. A strict type match there would report zero
        run time — a far more confusing failure than the equivalence is a risk."""
        by_number = MonitorTag(ref="C1", role=TagRole.RUN_STATE, running_when=(1,))
        by_bool = MonitorTag(ref="C1", role=TagRole.RUN_STATE, running_when=(True,))
        assert by_number.is_running(True) is True
        assert by_bool.is_running(1) is True
        assert by_number.is_running(False) is False
        assert by_bool.is_running(0) is False

    def test_running_when_without_the_run_state_role_is_refused(self):
        """It would have no meaning, and a reader would assume it did."""
        with pytest.raises(ValueError, match="(?i)running_when"):
            MonitorTag(ref="40010", role=TagRole.TOTAL_COUNT, running_when=(1,))


class TestParsingFromConfig:
    def test_roles_survive_the_yaml_round_trip(self):
        tags = parse_tags(
            [
                {"ref": "40001", "role": "run_state", "running_when": [2]},
                {"ref": "40010", "role": "total_count"},
                {"ref": "40012", "role": "good_count"},
            ]
        )
        assert [t.role for t in tags] == ["run_state", "total_count", "good_count"]

    def test_a_scalar_running_when_is_accepted(self):
        """`running_when: 2` is what someone will actually type."""
        tags = parse_tags([{"ref": "40001", "role": "run_state", "running_when": 2}])
        assert tags[0].running_when == (2,)

    def test_a_tag_without_a_role_still_parses(self):
        """Roles are additive — every existing config keeps working."""
        tags = parse_tags([{"ref": "40001", "warn_high": 80}])
        assert tags[0].role == "" and tags[0].warn_high == 80

    def test_a_bad_role_fails_the_config_rather_than_being_dropped(self):
        with pytest.raises(ValueError):
            parse_tags([{"ref": "x", "role": "typo_here"}])


class TestFindingTheRolesOnALine:
    def test_a_line_reports_which_roles_it_has(self):
        from iaiops.core.runtime.config import roles_present

        tags = parse_tags(
            [
                {"ref": "40001", "role": "run_state", "running_when": [2]},
                {"ref": "40010", "role": "total_count"},
            ]
        )
        assert roles_present(tags) == {"run_state": "40001", "total_count": "40010"}

    def test_two_tags_claiming_one_role_is_refused(self):
        """Which one is the production counter? Picking either is a guess, and
        the wrong pick produces a plausible number."""
        from iaiops.core.runtime.config import roles_present

        tags = parse_tags(
            [{"ref": "a", "role": "total_count"}, {"ref": "b", "role": "total_count"}]
        )
        with pytest.raises(ValueError, match="(?i)total_count"):
            roles_present(tags)
