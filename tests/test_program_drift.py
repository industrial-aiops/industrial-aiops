"""Program change baseline: what counts as drift, and what must never be cleared.

The value of this feature is a refusal, not a detection. Telling somebody their
control program changed is easy; the hard part is never telling them it did not
when it did. So the tests that matter here are the negative ones:

* ``identical`` requires the same SHA-256 — structure matching over different
  bytes must NOT earn that word, because these parsers extract structure rather
  than parse a grammar and a change they do not model looks the same from here;
* the fingerprint must not move for line shifts, comment edits or block
  reordering, or the tool cries wolf and gets switched off inside a week;
* the fingerprint must move for every category it claims to cover.

Both halves are needed. A fingerprint that never moves passes the first set; one
that always moves passes the second.
"""

from __future__ import annotations

import json
import stat

import pytest

from iaiops.core.brain import plc_program as ops
from iaiops.core.brain import program_baseline as pb
from iaiops.core.brain.plc_program import drift as dr
from iaiops.core.brain.plc_program import fingerprint as fpm

pytestmark = pytest.mark.unit

SCL = """\
// Conveyor control exported from TIA Portal
FUNCTION_BLOCK "FB_Conveyor"
VAR_INPUT
    Start : BOOL;   // start command
    Stop  : BOOL;   // stop command
END_VAR
VAR_OUTPUT
    Running : BOOL;
END_VAR
VAR
    RunTimer : TON;  // debounce timer
    Drive : "FB_Drive";
END_VAR
BEGIN
    IF Start AND NOT Stop THEN
        Running := TRUE;
    END_IF;
    RunTimer(IN := Running, PT := T#2s);
    Drive(Enable := RunTimer.Q);
END_FUNCTION_BLOCK

FUNCTION "FC_Scale" : REAL
VAR_INPUT
    Raw : INT;
END_VAR
BEGIN
    CASE Raw OF
        0: FC_Scale := 0.0;
    END_CASE;
END_FUNCTION
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated iaiops home so nothing touches the developer's own store."""
    h = tmp_path / "iaiops-home"
    monkeypatch.setenv("IAIOPS_HOME", str(h))
    return h


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, "utf-8")
    return str(path)


def _fingerprint(tmp_path, name: str, text: str) -> dict:
    return fpm.fingerprint_outline(ops.outline_program(_write(tmp_path, name, text)))


def _structure(tmp_path, name: str, text: str) -> str:
    return _fingerprint(tmp_path, name, text)["structure_fingerprint"]


# ─── the fingerprint must NOT move for noise ─────────────────────────────────


def test_a_comment_edit_does_not_move_the_fingerprint(tmp_path):
    edited = SCL.replace("// start command", "// start command (MOC-118: clarified)")
    assert _structure(tmp_path, "a.scl", SCL) == _structure(tmp_path, "b.scl", edited)


def test_a_leading_comment_line_does_not_move_the_fingerprint(tmp_path):
    """Every line number shifts. A fingerprint that moved would cry wolf."""
    shifted = "// exported 2026-09-01 by J. Operator\n" + SCL
    assert _structure(tmp_path, "a.scl", SCL) == _structure(tmp_path, "c.scl", shifted)


def test_reordering_the_blocks_does_not_move_the_fingerprint(tmp_path):
    first, second = SCL.split('\nFUNCTION "FC_Scale"')
    reordered = 'FUNCTION "FC_Scale"' + second + "\n" + first
    assert _structure(tmp_path, "a.scl", SCL) == _structure(tmp_path, "d.scl", reordered)


# ─── ...and MUST move for every category it claims to cover ──────────────────


@pytest.mark.parametrize(
    ("label", "mutated"),
    [
        (
            "variable added",
            SCL.replace("    Running : BOOL;\n", "    Running : BOOL;\n    Fault : BOOL;\n"),
        ),
        ("variable retyped", SCL.replace("Start : BOOL;", "Start : INT;")),
        ("branch condition changed", SCL.replace("IF Start AND NOT Stop THEN", "IF Start THEN")),
        ("call removed", SCL.replace("    Drive(Enable := RunTimer.Q);\n", "")),
        ("timer retyped", SCL.replace("RunTimer : TON;", "RunTimer : TOF;")),
    ],
)
def test_a_real_change_moves_the_fingerprint(tmp_path, label, mutated):
    assert mutated != SCL, f"the {label} fixture did not actually change the source"
    assert _structure(tmp_path, "a.scl", SCL) != _structure(tmp_path, "m.scl", mutated), label


def test_a_changed_block_names_the_categories_that_moved(tmp_path):
    mutated = SCL.replace(
        "    Running : BOOL;\n", "    Running : BOOL;\n    Fault : BOOL;\n"
    ).replace("IF Start AND NOT Stop THEN", "IF Start AND NOT Stop AND NOT Fault THEN")
    before = _fingerprint(tmp_path, "a.scl", SCL)
    after = _fingerprint(tmp_path, "b.scl", mutated)
    result = dr.compare(before, after, before_sha256="aaa", after_sha256="bbb")

    assert result["verdict"] == dr.VERDICT_LOGIC_CHANGED
    changed = result["blocks"]["changed"]
    assert [c["block"] for c in changed] == ["FB_Conveyor"]
    assert set(changed[0]["changed"]) == {"variables", "branches"}
    assert result["blocks"]["unchanged"] == 1


def test_added_and_removed_blocks_are_listed(tmp_path):
    extra = SCL + '\nFUNCTION "FC_New" : BOOL\nBEGIN\nEND_FUNCTION\n'
    before = _fingerprint(tmp_path, "a.scl", SCL)
    after = _fingerprint(tmp_path, "b.scl", extra)

    forward = dr.compare(before, after, before_sha256="a", after_sha256="b")
    assert [b["block"] for b in forward["blocks"]["added"]] == ["FC_New"]
    backward = dr.compare(after, before, before_sha256="b", after_sha256="a")
    assert [b["block"] for b in backward["blocks"]["removed"]] == ["FC_New"]


# ─── the word "identical" is earned by bytes, never by structure ─────────────


def test_matching_structure_over_different_bytes_is_not_identical(tmp_path):
    """The flattering answer is "nothing important changed". It is not available."""
    edited = SCL.replace("// start command", "// start command (reworded)")
    before = _fingerprint(tmp_path, "a.scl", SCL)
    after = _fingerprint(tmp_path, "b.scl", edited)

    result = dr.compare(before, after, before_sha256="aaa", after_sha256="bbb")

    assert result["verdict"] == dr.VERDICT_OUTSIDE_STRUCTURE
    assert result["verdict"] != dr.VERDICT_IDENTICAL
    assert result["content_changed"] is True
    assert result["structure_changed"] is False
    assert "not a clearance" in result["note"]
    assert "documentation only" not in result["note"].lower().replace("-", " ") or (
        "would be" in result["note"]
    )


def test_identical_requires_the_same_digest(tmp_path):
    before = _fingerprint(tmp_path, "a.scl", SCL)
    result = dr.compare(before, before, before_sha256="same", after_sha256="same")
    assert result["verdict"] == dr.VERDICT_IDENTICAL
    assert result["content_changed"] is False


def test_comparing_across_recipe_versions_is_refused(tmp_path):
    before = _fingerprint(tmp_path, "a.scl", SCL)
    stale = {**before, "recipe_version": before["recipe_version"] + 1}
    with pytest.raises(dr.RecipeMismatchError, match="artefact of the tool"):
        dr.compare(stale, before, before_sha256="a", after_sha256="b")


# ─── the store ───────────────────────────────────────────────────────────────


def test_snapshot_records_and_drift_finds_a_logic_change(tmp_path, home):
    path = _write(tmp_path, "conveyor.scl", SCL)
    taken = pb.take_snapshot(path, label="approved v1")

    assert taken["status"] == "recorded"
    assert taken["program"] == "conveyor"
    assert taken["name_source"] == "filename stem"
    assert taken["snapshot"]["snapshot_id"] == "conveyor-0001"

    changed = _write(
        tmp_path,
        "conveyor.scl",
        SCL.replace("IF Start AND NOT Stop THEN", "IF Start THEN"),
    )
    result = pb.check_drift(changed)

    assert result["verdict"] == dr.VERDICT_LOGIC_CHANGED
    assert result["baseline"]["snapshot_id"] == "conveyor-0001"
    assert result["baseline"]["label"] == "approved v1"


def test_an_unchanged_file_records_nothing(tmp_path, home):
    path = _write(tmp_path, "conveyor.scl", SCL)
    pb.take_snapshot(path)
    again = pb.take_snapshot(path)

    assert again["status"] == "unchanged"
    assert again["snapshot_count"] == 1
    assert pb.history("conveyor")["snapshot_count"] == 1


def test_the_program_name_survives_a_new_export_directory(tmp_path, home):
    """Keying on the path would file every export as a different program."""
    pb.take_snapshot(_write(tmp_path, "Line3.scl", SCL), name="Line3")
    other_dir = tmp_path / "monday"
    other_dir.mkdir()
    moved = other_dir / "Line3.scl"
    moved.write_text(SCL, "utf-8")

    result = pb.check_drift(str(moved), name="Line3")
    assert result["verdict"] == dr.VERDICT_IDENTICAL


def test_the_store_holds_block_names_but_no_source(tmp_path, home):
    """A store that carried the program would be a copy of it — and a leak.

    Block names ARE kept: a drift report that could not say *which* block moved
    would be useless. Everything below that level is a digest — declarations,
    source lines and comments never land on disk.
    """
    path = _write(tmp_path, "conveyor.scl", SCL)
    pb.take_snapshot(path)
    raw = pb.store_path().read_text("utf-8")

    assert "FB_Conveyor" in raw, "a drift report has to be able to name the block"
    for secret in ("RunTimer", "IF Start", "debounce", "VAR_INPUT", "T#2s"):
        assert secret not in raw, f"{secret!r} leaked into the baseline store"


def test_the_store_is_owner_only(tmp_path, home):
    pb.take_snapshot(_write(tmp_path, "conveyor.scl", SCL))
    mode = stat.S_IMODE(pb.store_path().stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_taking_a_snapshot_does_not_mutate_the_loaded_store(tmp_path, home):
    pb.take_snapshot(_write(tmp_path, "a.scl", SCL), name="a")
    loaded = pb.load_store()
    frozen = json.dumps(loaded, sort_keys=True)

    pb.take_snapshot(_write(tmp_path, "b.scl", SCL.replace("Stop", "Halt")), name="b")

    assert json.dumps(loaded, sort_keys=True) == frozen


def test_history_lists_every_tracked_program(tmp_path, home):
    pb.take_snapshot(_write(tmp_path, "a.scl", SCL), name="LineA")
    pb.take_snapshot(_write(tmp_path, "b.scl", SCL.replace("Stop", "Halt")), name="LineB")

    listing = pb.history()
    assert listing["program_count"] == 2
    assert [p["program"] for p in listing["programs"]] == ["LineA", "LineB"]


def test_compare_snapshots_diffs_two_stored_versions(tmp_path, home):
    pb.take_snapshot(_write(tmp_path, "c.scl", SCL), name="C")
    pb.take_snapshot(
        _write(tmp_path, "c.scl", SCL.replace("IF Start AND NOT Stop THEN", "IF Start THEN")),
        name="C",
    )
    result = pb.compare_snapshots("C", "C-0001", "C-0002")
    assert result["verdict"] == dr.VERDICT_LOGIC_CHANGED


def test_forget_keeps_the_requested_tail(tmp_path, home):
    for i in range(3):
        pb.take_snapshot(_write(tmp_path, "d.scl", SCL + f"\n// rev {i}\n"), name="D")
    dropped = pb.forget("D", keep=1)

    assert dropped["removed"] == 2
    assert dropped["kept"] == ["D-0003"]
    assert pb.history("D")["snapshot_count"] == 1


def test_forget_without_keep_drops_the_program(tmp_path, home):
    pb.take_snapshot(_write(tmp_path, "e.scl", SCL), name="E")
    assert pb.forget("E")["still_tracked"] is False
    assert pb.history()["program_count"] == 0


# ─── refusals teach ──────────────────────────────────────────────────────────


def test_drift_against_an_untracked_program_says_how_to_start(tmp_path, home):
    with pytest.raises(pb.ProgramNotTrackedError, match="program snapshot"):
        pb.check_drift(_write(tmp_path, "unknown.scl", SCL))


def test_an_unknown_snapshot_id_lists_the_known_ones(tmp_path, home):
    pb.take_snapshot(_write(tmp_path, "f.scl", SCL), name="F")
    with pytest.raises(pb.SnapshotNotFoundError, match="F-0001"):
        pb.check_drift(_write(tmp_path, "f.scl", SCL), name="F", against="F-9999")


def test_an_empty_program_name_is_refused(tmp_path, home):
    with pytest.raises(ValueError, match="cannot be empty"):
        pb.take_snapshot(_write(tmp_path, "g.scl", SCL), name="   ")


def test_a_corrupt_store_is_refused_rather_than_silently_reset(tmp_path, home):
    pb.store_path().parent.mkdir(parents=True, exist_ok=True)
    pb.store_path().write_text("{not json", "utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        pb.load_store()


# ─── the tools are governed ──────────────────────────────────────────────────


def test_the_new_tools_are_governed_and_read_classified():
    import mcp_server.tools.plc_program_tools as mod

    for name in ("plc_program_snapshot", "plc_program_drift", "plc_program_history"):
        fn = getattr(mod, name)
        assert getattr(fn, "_is_governed_tool", False), f"{name} is ungoverned"
        assert (fn.__doc__ or "").startswith("[READ]"), name


def test_deleting_history_is_not_an_mcp_tool():
    """Removing change-control evidence should not be one tool call away."""
    import mcp_server.tools.plc_program_tools as mod

    assert not hasattr(mod, "plc_program_forget")
