"""Every MCP tool that opens a host file the agent names reads only inside the roots.

#268 confined the two sensor file tools. The same hole was open in ten more: the
six ``plc_program_*`` tools (``plc_program_section`` returns up to 200 source lines
of any ``.txt`` it is pointed at), ``device_advisory_check`` (any YAML/JSON) and
the three tools with a ``db`` override (any SQLite file — and a path that did not
exist could be created by opening it). They now go through ``agent_readable_path``:
``$IAIOPS_HOME``, the config directory, and the directories the OPERATOR lists in
``IAIOPS_AGENT_READ_DIRS`` — never ``/``, the home directory, a world-writable
directory or a relative entry. The CLI is the operator's shell and is unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SECRET = "LEAKED-LINE-5be1"
PROGRAM = (
    "FUNCTION_BLOCK FB_Conveyor\n"
    "VAR_INPUT\n  Start : BOOL; (* " + SECRET + " *)\nEND_VAR\n"
    "IF Start THEN\n  Running := TRUE;\nEND_IF;\n"
    "END_FUNCTION_BLOCK\n"
)
ADVISORY = {
    "id": "ICSA-24-012-01",
    "vendor": "Siemens",
    "model": "S7-1500",
    "affected_below": "2.9.2",
    "title": "example",
    "source": "CISA ICS advisory ICSA-24-012-01",
}
DEVICE = {"ip": "10.0.0.5", "vendor": "Siemens", "model": "S7-1500", "firmware": "2.8.1"}


@pytest.fixture
def outside(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("outside-roots")


@pytest.fixture(autouse=True)
def _no_operator_dirs(monkeypatch):
    monkeypatch.delenv("IAIOPS_AGENT_READ_DIRS", raising=False)


def _refused(out: dict) -> str:
    error = str(out.get("error", ""))
    assert "outside" in error and "IAIOPS_AGENT_READ_DIRS" in error, out
    assert SECRET not in json.dumps(out, default=str)
    return error


def _plc_calls(path: str):
    from mcp_server.tools import plc_program_tools as t

    return {
        "outline": lambda: t.plc_program_outline(path=path),
        "xref": lambda: t.plc_program_xref(path=path, symbol="Running"),
        "section": lambda: t.plc_program_section(path=path, block="FB_Conveyor"),
        "visibility": lambda: t.plc_program_visibility(path=path),
        "snapshot": lambda: t.plc_program_snapshot(path=path, name="Line3"),
        "drift": lambda: t.plc_program_drift(path=path, name="Line3"),
    }


# ── PLC program tools ────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool", ["outline", "xref", "section", "visibility", "snapshot", "drift"])
def test_plc_program_tools_refuse_an_export_outside_the_roots(outside, tool):
    prog = outside / "Line3.scl"
    prog.write_text(PROGRAM, "utf-8")
    _refused(_plc_calls(str(prog))[tool]())


def test_plc_section_cannot_be_used_to_read_an_arbitrary_text_file(outside):
    notes = outside / "notes.txt"
    notes.write_text(f"FUNCTION_BLOCK FB_Conveyor\n{SECRET}\nEND_FUNCTION_BLOCK\n", "utf-8")
    _refused(_plc_calls(str(notes))["section"]())


def test_plc_tools_refuse_a_symlinked_escape(isolated_iaiops_home, outside):
    (outside / "Line3.scl").write_text(PROGRAM, "utf-8")
    (isolated_iaiops_home / "exports").symlink_to(outside, target_is_directory=True)
    _refused(_plc_calls(str(isolated_iaiops_home / "exports" / "Line3.scl"))["outline"]())


def test_plc_tools_refuse_dotdot_traversal(isolated_iaiops_home, outside):
    (outside / "Line3.scl").write_text(PROGRAM, "utf-8")
    climbing = isolated_iaiops_home / ".." / ".." / outside.parent.name / outside.name / "Line3.scl"
    _refused(_plc_calls(str(climbing))["outline"]())


def test_plc_tools_read_an_export_under_iaiops_home(isolated_iaiops_home):
    exports = isolated_iaiops_home / "exports"
    exports.mkdir()
    prog = exports / "Line3.scl"
    prog.write_text(PROGRAM, "utf-8")
    calls = _plc_calls(str(prog))
    assert calls["outline"]()["stats"]["blocks"] == 1
    assert calls["snapshot"]()["status"] == "recorded"
    assert calls["drift"]()["verdict"] == "identical"


# ── the operator's own list ──────────────────────────────────────────────────


def test_an_operator_listed_directory_is_readable(outside, monkeypatch):
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", str(outside))
    prog = outside / "Line3.scl"
    prog.write_text(PROGRAM, "utf-8")
    assert _plc_calls(str(prog))["outline"]()["stats"]["blocks"] == 1


def test_several_operator_dirs_split_on_the_path_separator(tmp_path_factory, monkeypatch):
    first, second = tmp_path_factory.mktemp("a"), tmp_path_factory.mktemp("b")
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", f"{first}{os.pathsep}{second}")
    (second / "Line3.scl").write_text(PROGRAM, "utf-8")
    assert "error" not in _plc_calls(str(second / "Line3.scl"))["outline"]()


@pytest.mark.parametrize("entry", ["HOME", "ROOT", "RELATIVE", "WORLD_WRITABLE"])
def test_an_operator_entry_too_broad_to_confine_is_ignored(tmp_path_factory, monkeypatch, entry):
    home = tmp_path_factory.mktemp("user-home")
    monkeypatch.setenv("HOME", str(home))
    target = home / "exports"
    target.mkdir()
    (target / "Line3.scl").write_text(PROGRAM, "utf-8")
    if entry == "WORLD_WRITABLE":
        os.chmod(target, 0o777)  # noqa: S103 — the point of the test
    value = {
        "HOME": str(home),
        "ROOT": "/",
        "RELATIVE": "exports",
        "WORLD_WRITABLE": str(target),
    }[entry]
    monkeypatch.chdir(home)
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", value)
    _refused(_plc_calls(str(target / "Line3.scl"))["outline"]())


# ── advisory library ─────────────────────────────────────────────────────────


def test_advisory_check_refuses_a_library_outside_the_roots(outside):
    from mcp_server.tools.asset_tools import device_advisory_check

    lib = outside / "advisories.json"
    lib.write_text(json.dumps([ADVISORY]), "utf-8")
    _refused(device_advisory_check(devices=[DEVICE], library_path=str(lib)))


def test_advisory_check_reads_a_library_under_iaiops_home(isolated_iaiops_home):
    from mcp_server.tools.asset_tools import device_advisory_check

    lib = isolated_iaiops_home / "advisories.json"
    lib.write_text(json.dumps([ADVISORY]), "utf-8")
    out = device_advisory_check(devices=[DEVICE], library_path=str(lib))
    assert out["summary"]["in_affected_range"] == 1, out


def test_an_advisory_yaml_error_does_not_quote_the_file(isolated_iaiops_home):
    from mcp_server.tools.asset_tools import device_advisory_check

    lib = isolated_iaiops_home / "advisories.yaml"
    lib.write_text(f"advisories: [{SECRET}\n", "utf-8")
    out = device_advisory_check(devices=[DEVICE], library_path=str(lib))
    assert "error" in out and SECRET not in out["error"]


# ── the local-store override (db=) ───────────────────────────────────────────


def _db_calls(db: str):
    from mcp_server.tools import overview_tools as t

    return {
        "site_readiness": lambda: t.site_readiness(db=db),
        "onboarding_status": lambda: t.onboarding_status(db=db),
        "onboarding_config_draft": lambda: t.onboarding_config_draft(db=db),
    }


@pytest.mark.parametrize("tool", ["site_readiness", "onboarding_status", "onboarding_config_draft"])
def test_db_override_outside_the_roots_is_refused_and_creates_nothing(outside, tool):
    target = outside / "planted.db"
    _refused(_db_calls(str(target))[tool]())
    assert not target.exists()
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("tool", ["site_readiness", "onboarding_status", "onboarding_config_draft"])
def test_db_override_under_iaiops_home_still_works_even_when_missing(isolated_iaiops_home, tool):
    target = isolated_iaiops_home / "none.db"
    out = _db_calls(str(target))[tool]()
    if tool == "onboarding_config_draft":  # an empty store has no scan to draft from
        assert "No scan has been stored" in out["error"], out
    else:
        assert "error" not in out, out
    assert not target.exists()


@pytest.mark.parametrize("tool", ["site_readiness", "onboarding_status", "onboarding_config_draft"])
def test_db_tools_do_not_modify_an_existing_database(isolated_iaiops_home, tool):
    """Reading must not write: the scan listing used to add its tables and flip
    the journal mode of whatever database it was pointed at — the audit store
    included."""
    import sqlite3

    target = isolated_iaiops_home / "vendor_project.db"
    conn = sqlite3.connect(target)
    conn.execute("CREATE TABLE recipes (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()
    before = target.read_bytes()
    _db_calls(str(target))[tool]()
    conn = sqlite3.connect(target)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert tables == {"recipes"} and mode == "delete"
    assert target.read_bytes() == before


def test_the_default_store_is_unaffected():
    from mcp_server.tools import overview_tools as t

    assert "error" not in t.site_readiness()


# ── the CLI is the operator's shell ──────────────────────────────────────────


def test_cli_program_outline_still_reads_any_path(outside):
    from typer.testing import CliRunner

    from iaiops.cli import app

    prog = outside / "Line3.scl"
    prog.write_text(PROGRAM, "utf-8")
    result = CliRunner().invoke(app, ["program", "outline", str(prog)])
    assert result.exit_code == 0, result.output
    assert "FB_Conveyor" in result.output


# ── review round: further ways around the roots ──────────────────────────────


def test_historian_push_sqlite_cannot_write_outside_the_roots(outside):
    from mcp_server.tools.compliance_tools import historian_push

    before = oct(outside.stat().st_mode)
    out = historian_push(
        points=[{"ref": "a", "value": 1}], sink="sqlite", database=str(outside / "planted.db")
    )
    _refused(out)
    assert list(outside.iterdir()) == []
    assert oct(outside.stat().st_mode) == before


def test_historian_push_sqlite_writes_under_iaiops_home(isolated_iaiops_home):
    from mcp_server.tools.compliance_tools import historian_push

    target = isolated_iaiops_home / "lab.db"
    out = historian_push(points=[{"ref": "a", "value": 1}], sink="sqlite", database=str(target))
    assert out.get("written") == 1, out
    assert target.exists()


def test_a_symlinked_operator_entry_to_home_is_ignored(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("user-home3")
    monkeypatch.setenv("HOME", str(home))
    (home / "Line3.scl").write_text(PROGRAM, "utf-8")
    alias = tmp_path_factory.mktemp("alias") / "to-home"
    alias.symlink_to(home, target_is_directory=True)
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", str(alias))
    _refused(_plc_calls(str(home / "Line3.scl"))["outline"]())


def _case_insensitive(path: Path) -> bool:
    flipped = Path(str(path).swapcase())
    return flipped != path and flipped.exists()


def test_a_case_variant_of_home_is_still_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("CaseHome")
    if not _case_insensitive(home):
        pytest.skip("case-sensitive file system")
    monkeypatch.setenv("HOME", str(home))
    (home / "Line3.scl").write_text(PROGRAM, "utf-8")
    variant = str(home).swapcase()
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", variant)
    _refused(_plc_calls(str(Path(variant) / "Line3.scl"))["outline"]())


def test_a_group_writable_operator_dir_is_ignored(outside, monkeypatch):
    os.chmod(outside, 0o770)
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", str(outside))
    (outside / "Line3.scl").write_text(PROGRAM, "utf-8")
    _refused(_plc_calls(str(outside / "Line3.scl"))["outline"]())


def test_the_remedy_survives_the_error_cap_with_long_roots(tmp_path_factory, monkeypatch, outside):
    deep = [tmp_path_factory.mktemp("r" * 60) for _ in range(3)]
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", os.pathsep.join(str(d) for d in deep))
    (outside / "Line3.scl").write_text(PROGRAM, "utf-8")
    error = _refused(_plc_calls(str(outside / "Line3.scl"))["outline"]())
    assert "ask the operator" in error and "from a shell" in error
