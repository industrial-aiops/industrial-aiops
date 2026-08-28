"""Point-list semantic confirmation as a table.

HLD §10.1 named this and then nobody built it: point-list confirmation is
naturally a table, and *the CLI need only export a CSV, let a person edit it, and
import it back*. The App page was ordered "after" — and this, the CLI fallback it
was supposed to rest on, did not exist either. Until now the only way to say
"this tag is the production counter" was hand-editing `role:` in config.yaml,
exactly the method §10.1 says stops working at a hundred rows.

**Why it emits a config patch rather than storing its own declarations.** The
first version stored roles as `declared` facts with an author, the way `relations
declare` and `knowledge mount` do. That was wrong here because of a coupling:
`oee measure` reads `role` off the config tag OBJECTS, and `MonitorTag` refuses a
`run_state` that does not also carry `running_when`. A parallel store would have
let `readiness` report the mapping as met while `oee measure` still could not
run — the flattering error this product keeps having to remove.
"""

from __future__ import annotations

import pytest
import yaml

from iaiops.core.runtime.tag_sheet import (
    SHEET_COLUMNS,
    config_patch,
    sheet_rows,
    validate_rows,
)

pytestmark = pytest.mark.unit


class FakeTag:
    def __init__(self, ref, label="", role="", running_when=()):
        self.ref = ref
        self.label = label
        self.role = role
        self.running_when = running_when


class FakeTarget:
    def __init__(self, name, tags):
        self.name = name
        self.protocol = "opcua"
        self.tags = tags


class FakeConfig:
    def __init__(self, targets):
        self.targets = targets


def site():
    return FakeConfig(
        [
            FakeTarget(
                "line1",
                [
                    FakeTag("ns=2;i=5", "GoodPartsCounter"),
                    FakeTag("ns=2;i=6", "Machine running"),
                    FakeTag("ns=2;i=7", "Temperature"),
                ],
            ),
            FakeTarget("line2", [FakeTag("40001", "TotalCount", role="total_count")]),
        ]
    )


def row(**over):
    base = {"endpoint": "line1", "ref": "ns=2;i=5", "label": "", "role": "total_count"}
    base.update(over)
    return base


class TestTheSheetNeverSuggests:
    """The refusal that matters most, at the exact place guessing is most
    tempting: a column called `role` beside a tag called `GoodPartsCounter`."""

    def test_every_row_ships_with_an_empty_role(self):
        assert all(r["role"] == "" for r in sheet_rows(site()))

    def test_a_tag_named_after_a_role_is_still_left_empty(self):
        """A name is not a declaration. Plenty of plants have a
        `GoodPartsCounter` that counts something else."""
        found = next(r for r in sheet_rows(site()) if r["label"] == "GoodPartsCounter")
        assert found["role"] == "", found

    def test_an_existing_declaration_is_shown_but_not_pre_filled(self):
        """The reader has to see what config already says; putting it in the
        editable column would make re-applying an untouched sheet re-declare
        everything, and a no-op would read as a confirmation."""
        found = next(r for r in sheet_rows(site()) if r["ref"] == "40001")
        assert found["declared_role"] == "total_count" and found["role"] == ""

    def test_it_lists_every_monitored_tag_with_its_endpoint(self):
        rows = sheet_rows(site())
        assert len(rows) == 4 and {r["endpoint"] for r in rows} == {"line1", "line2"}

    def test_the_columns_are_stable(self):
        assert SHEET_COLUMNS[0] == "endpoint"
        assert "role" in SHEET_COLUMNS and "running_when" in SHEET_COLUMNS


class TestRunStateNeedsRunningWhen:
    """`MonitorTag` refuses a run_state with no `running_when`. Refused here too,
    so a sheet cannot emit a patch that config would then reject — and so the
    person is told at the point they can still answer."""

    def test_a_run_state_without_running_when_is_refused(self):
        with pytest.raises(ValueError, match="running_when"):
            validate_rows([row(ref="ns=2;i=6", role="run_state")], site())

    def test_the_refusal_explains_the_trap_rather_than_just_naming_the_field(self):
        with pytest.raises(ValueError, match="idle and fault"):
            validate_rows([row(ref="ns=2;i=6", role="run_state")], site())

    def test_with_running_when_it_is_accepted(self):
        edits = validate_rows([row(ref="ns=2;i=6", role="run_state", running_when="2")], site())
        assert edits[0].running_when == ("2",)

    def test_several_running_values_are_accepted(self):
        edits = validate_rows([row(ref="ns=2;i=6", role="run_state", running_when="2, 3")], site())
        assert edits[0].running_when == ("2", "3")

    def test_running_when_on_a_counter_is_refused(self):
        """It means nothing there, and accepting it silently would teach the
        reader that it does."""
        with pytest.raises(ValueError, match="run_state"):
            validate_rows([row(running_when="2")], site())


class TestTheOtherRefusals:
    def test_an_unknown_role_is_refused_and_names_the_ones_that_exist(self):
        with pytest.raises(ValueError, match="run_state"):
            validate_rows([row(role="throughput")], site())

    def test_a_ref_nobody_monitors_is_refused(self):
        """A typo would otherwise put a role on a tag that is not collected, and
        readiness would report the gap as filled while nothing fills it."""
        with pytest.raises(ValueError, match="ns=2;i=99"):
            validate_rows([row(ref="ns=2;i=99")], site())

    def test_one_role_claimed_by_two_tags_is_refused(self):
        rows = [row(), row(ref="ns=2;i=7")]
        with pytest.raises(ValueError, match="total_count"):
            validate_rows(rows, site())

    def test_the_same_tag_repeated_with_the_same_role_is_not_a_conflict(self):
        assert len(validate_rows([row(), row()], site())) == 2

    def test_a_row_with_no_ref_is_refused(self):
        with pytest.raises(ValueError, match="ref"):
            validate_rows([row(ref="")], None)


class TestABlankCellChangesNothing:
    """A sheet that has been through a spreadsheet loses cells routinely.
    Blank-means-withdraw would delete semantics somebody spent an afternoon on."""

    def test_blank_rows_are_skipped(self):
        assert validate_rows([row(role="")], site()) == ()

    def test_a_sheet_of_blanks_produces_no_patch_rather_than_an_empty_one(self):
        assert config_patch(validate_rows([row(role="")], site())) == ""

    def test_the_filled_rows_around_a_blank_one_still_apply(self):
        edits = validate_rows([row(role=""), row()], site())
        assert [e.ref for e in edits] == ["ns=2;i=5"]


class TestThePatchIsUsable:
    """The strongest check available: what comes out has to be something config
    would actually accept. A patch that only looks right is the failure here."""

    def _patch(self):
        edits = validate_rows(
            [
                row(ref="ns=2;i=6", role="run_state", running_when="2"),
                row(ref="ns=2;i=5", role="total_count"),
            ],
            site(),
        )
        return config_patch(edits, by="wei")

    def test_it_parses_as_yaml(self):
        parsed = yaml.safe_load(self._patch())
        assert isinstance(parsed, list) and len(parsed) == 2

    def test_every_entry_survives_the_real_tag_constructor(self):
        """`MonitorTag.__post_init__` is where a run_state with no running_when
        is rejected. Round-tripping through it proves the patch is not merely
        well-formed text."""
        from iaiops.core.runtime.config import MonitorTag

        for entry in yaml.safe_load(self._patch()):
            tag = MonitorTag(**entry)
            assert tag.role

    def test_the_run_state_keeps_its_running_when(self):
        from iaiops.core.runtime.config import MonitorTag

        tags = [MonitorTag(**e) for e in yaml.safe_load(self._patch())]
        run_state = next(t for t in tags if t.role == "run_state")
        assert list(run_state.running_when) == [2], run_state.running_when

    def test_it_records_who_confirmed(self):
        """config.yaml has nowhere else to say who decided a tag counts
        production; the comment is the only place that survives the paste."""
        assert "wei" in self._patch()

    def test_it_says_where_to_put_it(self):
        assert "config.yaml" in self._patch()

    def test_endpoints_are_kept_apart(self):
        edits = validate_rows(
            [row(), {"endpoint": "line2", "ref": "40001", "role": "good_count"}], site()
        )
        patch = config_patch(edits)
        assert "line1" in patch and "line2" in patch
        assert patch.index("line1") < patch.index("line2")

    def test_a_numeric_ref_survives_the_round_trip_as_a_string(self):
        """`ref: 40001` re-parses as an INT and then matches no tag. Found by
        running the round trip; every assertion about the patch TEXT passed while
        the patch was unusable."""
        patch = config_patch(
            validate_rows([{"endpoint": "line2", "ref": "40001", "role": "good_count"}], site())
        )
        entry = yaml.safe_load(patch)[0]
        assert entry["ref"] == "40001", entry
        assert isinstance(entry["ref"], str), type(entry["ref"])
