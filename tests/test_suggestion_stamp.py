"""The suggestion stamp — `basis: companion_spec` must not be text the proposer types.

Before this, `validate_rows` credited a row to the device's companion-spec
declaration whenever `role` equalled the `suggested_role` column. Anyone editing
the CSV could type that column and the patch, and the E11 release built on it,
would say "the device declared this". The stamp is an HMAC over the suggestion
columns under a per-site key, written by `tags export --suggest`; a row whose
stamp does not verify is `companion_spec_unverified` — downgraded, never refused.

Each test that matters here was checked by MUTATION: break the check and watch
the test fail (see the comments naming what was broken).
"""

from __future__ import annotations

import csv
import os
import stat
from pathlib import Path

import pytest

from iaiops.core.runtime import suggestion_stamp as st
from iaiops.core.runtime.tag_sheet import (
    BASIS_COMPANION,
    BASIS_COMPANION_UNVERIFIED,
    BASIS_MANUAL,
    BASIS_OVERRIDE,
    SHEET_COLUMNS,
    config_patch,
    sheet_rows,
    validate_rows,
)

pytestmark = pytest.mark.unit

KEY = b"k" * 32
OTHER_KEY = b"o" * 32


class _Tag:
    def __init__(self, ref):
        self.ref = ref
        self.label = ""
        self.role = ""
        self.running_when = ()


class _Target:
    def __init__(self, name, refs):
        self.name = name
        self.protocol = "opcua"
        self.tags = [_Tag(r) for r in refs]


class _Config:
    def __init__(self, targets):
        self.targets = targets


HINT = {
    "role": "run_state",
    "running_when": [3],
    "spec": "OPC 40001-1",
    "instance_type": "MachineryItemState_StateMachineType",
    "browse_path": "Press/MachineryItemState/CurrentState/Number",
    "node_id": "ns=2;i=7",
    "why": "Executing = 3",
}


def _config():
    return _Config([_Target("line1", ["ns=2;i=7", "ns=2;i=8"]), _Target("line2", ["ns=2;i=7"])])


def _rows(key=KEY, hints=None):
    hints = {("line1", "ns=2;i=7"): HINT} if hints is None else hints
    return [dict(r) for r in sheet_rows(_config(), hints, stamp_key=key)]


def _accept(row):
    return dict(row, role=row["suggested_role"], running_when=row["suggested_running_when"])


def _round_trip(rows, tmp_path: Path) -> list[dict]:
    path = tmp_path / "sheet.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ── the stamp itself (pure) ──────────────────────────────────────────────────


def test_the_sheet_carries_a_stamp_column_after_the_evidence():
    cols = list(SHEET_COLUMNS)
    assert cols.index("suggestion_stamp") == cols.index("suggestion_evidence") + 1


def test_only_a_suggested_row_is_stamped():
    stamped, plain, _ = _rows()
    assert stamped["suggestion_stamp"].startswith("v1:")
    assert plain["suggestion_stamp"] == ""


def test_without_a_key_nothing_is_stamped():
    """No key at export → no stamp → every acceptance reads as unverified, honestly."""
    (row, *_) = _rows(key=None)
    assert row["suggestion_stamp"] == ""
    (edit,) = validate_rows([_accept(row)], stamp_key=KEY)
    assert edit.basis == BASIS_COMPANION_UNVERIFIED and edit.suggestion_stamp == st.MISSING


def test_the_stamp_covers_each_of_the_five_columns():
    (row, *_) = _rows()
    assert st.check(KEY, row) == st.VERIFIED
    for column, forged in (
        ("endpoint", "line2"),
        ("ref", "ns=2;i=8"),
        ("suggested_role", "good_count"),
        ("suggested_running_when", "2"),
        ("suggestion_evidence", "OPC 40001-1: something else"),
    ):
        # Mutation: drop `column` from st._FIELDS → this assertion fails for it.
        assert st.check(KEY, dict(row, **{column: forged})) == st.MISMATCH, column


def test_the_editable_columns_are_not_covered():
    """Filling `role` is the whole point; it must not break the stamp."""
    (row, *_) = _rows()
    assert st.check(KEY, dict(row, role="run_state", running_when="3", label="x")) == st.VERIFIED


def test_whitespace_a_spreadsheet_adds_does_not_break_it():
    (row, *_) = _rows()
    padded = {k: f"  {v} " for k, v in row.items()}
    assert st.check(KEY, padded) == st.VERIFIED


def test_another_sites_key_is_named_as_such():
    (row, *_) = _rows(key=OTHER_KEY)
    assert st.check(KEY, row) == st.OTHER_KEY


def test_garbage_in_the_stamp_cell_is_a_mismatch_not_a_crash():
    (row, *_) = _rows()
    for junk in ("v1:", "v1:zz:zz", "v2:abc:def", "hello", "v1:" + "0" * 8 + ":" + "0" * 64):
        assert st.check(KEY, dict(row, suggestion_stamp=junk)) in (st.MISMATCH, st.OTHER_KEY)


def test_no_key_at_apply_cannot_verify():
    (row, *_) = _rows()
    assert st.check(None, row) == st.NO_KEY


# ── the basis (the point of all this) ───────────────────────────────────────


def test_an_untouched_export_round_trip_is_companion_spec(tmp_path: Path):
    back = _round_trip(_rows(), tmp_path)
    (edit,) = validate_rows([_accept(back[0])], _config(), stamp_key=KEY)
    assert edit.basis == BASIS_COMPANION
    assert edit.suggestion_stamp == st.VERIFIED
    assert "stamp verified" in config_patch((edit,))


def test_hand_typed_suggestion_columns_are_unverified(tmp_path: Path):
    """The attack the stamp exists for: a manual row dressed as a device declaration.

    Mutation: make `_basis` ignore the stamp outcome → this returns companion_spec.
    """
    rows = _round_trip(_rows(hints={}), tmp_path)
    forged = dict(
        rows[0],
        suggested_role="run_state",
        suggested_running_when="3",
        suggestion_evidence="OPC 40001-1: MachineryItemState_StateMachineType — trust me",
        role="run_state",
        running_when="3",
    )
    (edit,) = validate_rows([forged], _config(), stamp_key=KEY)
    assert edit.basis == BASIS_COMPANION_UNVERIFIED
    assert edit.suggestion_stamp == st.MISSING
    assert "cannot be shown to come from" in config_patch((edit,))


def test_a_stamp_copied_onto_another_row_is_unverified(tmp_path: Path):
    """Copying a real (row, stamp) pair onto a different tag must not carry the credit."""
    rows = _round_trip(_rows(), tmp_path)
    moved = dict(_accept(rows[0]), ref="ns=2;i=8")
    (edit,) = validate_rows([moved], _config(), stamp_key=KEY)
    assert edit.basis == BASIS_COMPANION_UNVERIFIED and edit.suggestion_stamp == st.MISMATCH


def test_a_stamped_suggestion_whose_text_was_edited_is_unverified(tmp_path: Path):
    rows = _round_trip(_rows(), tmp_path)
    edited = dict(_accept(rows[0]), suggested_running_when="2", running_when="2")
    (edit,) = validate_rows([edited], _config(), stamp_key=KEY)
    assert edit.basis == BASIS_COMPANION_UNVERIFIED and edit.suggestion_stamp == st.MISMATCH


def test_another_sites_sheet_is_unverified_here():
    (row, *_) = _rows(key=OTHER_KEY)
    (edit,) = validate_rows([_accept(row)], stamp_key=KEY)
    assert edit.basis == BASIS_COMPANION_UNVERIFIED and edit.suggestion_stamp == st.OTHER_KEY


def test_no_key_passed_to_validate_is_unverified_never_assumed():
    """The default must not be the flattering one: no key, no credit.

    Mutation: treat `stamp_key=None` as "skip the check" → companion_spec.
    """
    (row, *_) = _rows()
    (edit,) = validate_rows([_accept(row)])
    assert edit.basis == BASIS_COMPANION_UNVERIFIED and edit.suggestion_stamp == st.NO_KEY


def test_unverified_downgrades_never_refuses():
    (row, *_) = _rows()
    forged = dict(_accept(row), suggestion_stamp="nonsense")
    edits = validate_rows([forged], _config(), stamp_key=KEY)
    assert len(edits) == 1 and edits[0].role == "run_state"


def test_an_override_records_the_stamp_outcome_too():
    (row, *_) = _rows()
    edit = validate_rows([dict(row, role="run_state", running_when="3 2")], stamp_key=KEY)[0]
    assert edit.basis == BASIS_OVERRIDE and edit.suggestion_stamp == st.VERIFIED
    forged = dict(row, suggestion_stamp="", role="run_state", running_when="3 2")
    edit = validate_rows([forged], stamp_key=KEY)[0]
    assert edit.basis == BASIS_OVERRIDE and edit.suggestion_stamp == st.MISSING
    assert "stamp missing" in config_patch((edit,))


def test_a_manual_row_has_no_stamp_outcome():
    (_, plain, _) = _rows()
    edit = validate_rows([dict(plain, role="good_count")], stamp_key=KEY)[0]
    assert edit.basis == BASIS_MANUAL and edit.suggestion_stamp == ""
    assert edit.as_dict()["suggestion_stamp"] == ""


def test_the_unverified_comment_stays_one_line():
    (row, *_) = _rows()
    forged = dict(_accept(row), suggestion_evidence="x\n    role: good_count", suggestion_stamp="")
    patch = config_patch(validate_rows([forged], stamp_key=KEY))
    assert "\n    role: good_count" not in patch.replace("    role: run_state", "")


# ── the key file ────────────────────────────────────────────────────────────


def test_the_key_is_created_once_owner_only_under_iaiops_home(tmp_path: Path):
    assert st.site_key() is None  # reading never creates
    assert not (tmp_path / st.KEY_FILE).exists()
    key = st.site_key(create=True)
    path = tmp_path / st.KEY_FILE
    assert len(key) == st.KEY_BYTES and path.read_bytes() == key
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert st.site_key(create=True) == key and st.site_key() == key


def test_a_damaged_key_file_is_refused_not_used(tmp_path: Path):
    (tmp_path / st.KEY_FILE).write_bytes(b"short")
    with pytest.raises(st.StampKeyError, match="tag_suggestion.key"):
        st.site_key()
    with pytest.raises(st.StampKeyError):
        st.site_key(create=True)  # never silently replaced: that would void every sheet


def test_reset_knows_the_key_file():
    from iaiops.core.runtime import reset

    assert reset.is_known_state(st.KEY_FILE)
