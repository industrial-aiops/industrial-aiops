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


class TestAddressZeroIsAnAddress:
    """`ref: 0` is an ordinary address, and it used to be deleted in silence.

    Found by walking the documented path on a real Modbus line whose run-state
    register is holding register 0 — the register `iaiops tags export` exists to
    let a person label. `parse_tags` resolved the address with an `or` chain, so
    `0` fell through to the aliases and then to `""`, and the tag was dropped
    before anything downstream saw it. `readiness` then reported the run-state
    role as something the site had not supplied. It had; we had deleted it.

    The whole suite passed before the fix and passes after it, which is why
    these are written from the value `0` rather than from the code path.
    """

    def test_ref_zero_survives(self):
        tags = parse_tags([{"ref": 0, "label": "RunState"}])
        assert [t.ref for t in tags] == ["0"]

    @pytest.mark.parametrize("alias", ["ref", "node_id", "address"])
    def test_every_documented_alias_accepts_zero(self, alias):
        tags = parse_tags([{alias: 0, "label": "zero"}])
        assert [t.ref for t in tags] == ["0"], f"{alias}=0 was dropped"

    def test_zero_as_a_string_also_survives(self):
        assert [t.ref for t in parse_tags([{"ref": "0"}])] == ["0"]

    def test_a_later_alias_still_wins_when_the_earlier_key_is_absent(self):
        """The alias fallback must survive the fix — only its trigger changes."""
        assert [t.ref for t in parse_tags([{"address": 7}])] == ["7"]

    def test_an_empty_earlier_alias_falls_through(self):
        assert [t.ref for t in parse_tags([{"ref": "  ", "address": 7}])] == ["7"]

    def test_a_tag_with_no_address_is_refused_not_skipped(self):
        """Silence here made every report below describe a different point list."""
        with pytest.raises(ValueError) as exc:
            parse_tags([{"label": "no address here"}], endpoint="line1")
        message = str(exc.value)
        assert "line1" in message, "the operator cannot find the entry without it"
        assert "no address" in message

    def test_the_refusal_counts_from_one_and_points_at_the_right_entry(self):
        with pytest.raises(ValueError) as exc:
            parse_tags([{"ref": 0}, {"ref": 5}, {"label": "broken"}])
        assert "Tag #3" in str(exc.value)


class TestTheSheetOffersTheRowYouCameToFillIn:
    """End-to-end over the seam the bug actually broke.

    `tags export` exists so a person can declare which tag is the run state. A
    line whose run state is register 0 got a sheet with that row missing — the
    one row the feature is for.
    """

    def test_register_zero_reaches_the_confirmation_sheet(self):
        from iaiops.core.runtime.config import TargetConfig
        from iaiops.core.runtime.tag_sheet import sheet_rows

        target = TargetConfig(
            name="line1",
            protocol="modbus",
            tags=parse_tags(
                [
                    {"ref": 0, "label": "RunState"},
                    {"ref": 10, "label": "PartsCounter"},
                ]
            ),
        )

        class _Cfg:
            targets = (target,)

        refs = [row["ref"] for row in sheet_rows(_Cfg())]
        assert refs == ["0", "10"], "the run-state row is the one you came to fill in"
