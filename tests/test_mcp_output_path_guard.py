"""MCP tools that WRITE a file the agent names stay inside the agent's write roots.

The 0.31.0 pre-release audit found the read side confined (#268/#270) but the
write side checked only for ``..``: ``export_data(fmt="sqlite",
out_path="~/.iaiops/audit.db")`` unlinked the audit hash-chain database at
risk=low, and the csv/json/md writers overwrote any host file with that suffix.
Writes now go through ``agent_writable_path``: ``$IAIOPS_HOME/exports`` plus the
private directories the OPERATOR lists in ``IAIOPS_AGENT_WRITE_DIRS`` — never a
directory that overlaps the product's own state.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_operator_dirs(monkeypatch):
    monkeypatch.delenv("IAIOPS_AGENT_WRITE_DIRS", raising=False)
    monkeypatch.delenv("IAIOPS_AGENT_READ_DIRS", raising=False)


@pytest.fixture(autouse=True)
def _seeded_store(isolated_iaiops_home):
    """A site that has collected something — otherwise export refuses before writing,
    and the tests would pass for the wrong reason."""
    from iaiops.core.sink.push import historian_push
    from iaiops.core.sink.sqlite_local import local_db_path

    out = historian_push(
        [{"ref": "40001", "value": 1.0}],
        "sqlite",
        db_path=local_db_path(),
        endpoint="plc1",
        protocol="modbus",
    )
    assert "error" not in out, out


@pytest.fixture
def outside(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("outside-write-roots")


@pytest.fixture
def audit_db(isolated_iaiops_home) -> Path:
    from iaiops.core.governance.audit import AuditEngine

    AuditEngine().log(skill="iaiops", tool="t", params={"i": 1})
    path = isolated_iaiops_home / "audit.db"
    assert path.exists()
    return path


def _refused(out: dict) -> str:
    error = str(out.get("error", ""))
    assert "Not written" in error and "IAIOPS_AGENT_WRITE_DIRS" in error, out
    return error


def _audit_intact(path: Path, tables_before: set[str]) -> None:
    """The refused call is itself audited (a new row), so bytes change by design —
    what must hold: same tables (no `samples` planted), and the chain verifies."""
    from iaiops.core.governance.audit import AuditEngine

    assert _tables(path) == tables_before
    assert AuditEngine().verify_chain()["ok"] is True


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


# ── the finding itself ───────────────────────────────────────────────────────


def test_export_cannot_replace_the_audit_database(audit_db):
    from mcp_server.tools.export_tools import export_data

    before = _tables(audit_db)
    _refused(export_data(fmt="sqlite", out_path=str(audit_db)))
    _audit_intact(audit_db, before)


@pytest.mark.parametrize("name", ["undo.db", "data.db"])
def test_export_cannot_replace_other_product_stores(isolated_iaiops_home, name):
    from mcp_server.tools.export_tools import export_data

    store = isolated_iaiops_home / name
    sqlite3.connect(store).close()
    before = store.read_bytes()
    _refused(export_data(fmt="sqlite", out_path=str(store)))
    assert store.read_bytes() == before


def test_export_cannot_overwrite_a_host_file(isolated_iaiops_home, outside):
    from mcp_server.tools.export_tools import export_data

    victim = outside / "notes.csv"
    victim.write_text("keep me\n", "utf-8")
    _refused(export_data(fmt="csv", out_path=str(victim)))
    assert victim.read_text("utf-8") == "keep me\n"


def test_export_default_path_still_works(isolated_iaiops_home):
    from mcp_server.tools.export_tools import export_data

    out = export_data(fmt="csv")
    assert "error" not in out, out
    assert Path(out["path"]).resolve().is_relative_to((isolated_iaiops_home / "exports").resolve())


def test_export_into_the_exports_directory_works(isolated_iaiops_home):
    from mcp_server.tools.export_tools import export_data

    target = isolated_iaiops_home / "exports" / "mine.csv"
    out = export_data(fmt="csv", out_path=str(target))
    assert "error" not in out, out
    assert target.exists()


def test_a_symlink_in_exports_cannot_point_out(isolated_iaiops_home, outside):
    from mcp_server.tools.export_tools import export_data

    victim = outside / "notes.csv"
    victim.write_text("keep me\n", "utf-8")
    exports = isolated_iaiops_home / "exports"
    exports.mkdir(exist_ok=True)
    (exports / "link.csv").symlink_to(victim)
    _refused(export_data(fmt="csv", out_path=str(exports / "link.csv")))
    assert victim.read_text("utf-8") == "keep me\n"


def test_dotdot_out_of_exports_is_refused(isolated_iaiops_home):
    from mcp_server.tools.export_tools import export_data

    path = str(isolated_iaiops_home / "exports" / ".." / "data.db")
    out = export_data(fmt="sqlite", out_path=path)
    assert "error" in out, out


# ── the other three writers ──────────────────────────────────────────────────


def test_compliance_report_cannot_write_outside(isolated_iaiops_home, outside):
    from mcp_server.tools.compliance_tools import compliance_report

    _refused(compliance_report(out_path=str(outside / "report.md")))
    assert list(outside.iterdir()) == []


def test_evidence_bundle_cannot_write_outside(isolated_iaiops_home, outside):
    from mcp_server.tools.compliance_tools import compliance_evidence_bundle

    _refused(compliance_evidence_bundle(out_path=str(outside / "evidence.zip")))
    assert list(outside.iterdir()) == []


def test_alarm_worksheet_cannot_write_outside(isolated_iaiops_home, outside):
    from mcp_server.tools.alarm_tools import alarm_rationalization_worksheet

    events = [{"tag": "TI101", "ts": "2026-10-18T00:00:00Z", "state": "active"}]
    _refused(alarm_rationalization_worksheet(events=events, out_path=str(outside / "w.csv")))
    assert list(outside.iterdir()) == []


# ── operator-listed write roots ──────────────────────────────────────────────


def _private_dir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir()
    os.chmod(d, 0o700)
    return d


def test_an_operator_write_dir_is_honoured(isolated_iaiops_home, tmp_path_factory, monkeypatch):
    from mcp_server.tools.export_tools import export_data

    d = _private_dir(tmp_path_factory.mktemp("op"), "exports")
    monkeypatch.setenv("IAIOPS_AGENT_WRITE_DIRS", str(d))
    out = export_data(fmt="csv", out_path=str(d / "x.csv"))
    assert "error" not in out, out


def test_a_group_writable_operator_dir_is_ignored(
    isolated_iaiops_home, tmp_path_factory, monkeypatch
):
    from mcp_server.tools.export_tools import export_data

    d = _private_dir(tmp_path_factory.mktemp("op"), "shared")
    os.chmod(d, 0o770)
    monkeypatch.setenv("IAIOPS_AGENT_WRITE_DIRS", str(d))
    _refused(export_data(fmt="csv", out_path=str(d / "x.csv")))


def test_an_operator_dir_overlapping_product_state_is_ignored(audit_db, monkeypatch):
    from mcp_server.tools.export_tools import export_data

    home = audit_db.parent
    os.chmod(home, 0o700)
    monkeypatch.setenv("IAIOPS_AGENT_WRITE_DIRS", str(home))
    before = _tables(audit_db)
    _refused(export_data(fmt="sqlite", out_path=str(audit_db)))
    _audit_intact(audit_db, before)


# ── historian_push into a product store ─────────────────────────────────────


@pytest.mark.parametrize("name", ["audit.db", "undo.db"])
def test_historian_push_refuses_a_product_store(audit_db, name):
    from mcp_server.tools.compliance_tools import historian_push

    store = audit_db.parent / name
    if not store.exists():
        sqlite3.connect(store).execute("CREATE TABLE other (x)").connection.close()
    before = _tables(store)
    out = historian_push(points=[{"ref": "a", "value": 1}], sink="sqlite", database=str(store))
    assert "error" in out and "product" in str(out["error"]).lower(), out
    assert _tables(store) == before and "samples" not in before


def test_historian_push_refuses_a_foreign_database_in_home(isolated_iaiops_home):
    from mcp_server.tools.compliance_tools import historian_push

    store = isolated_iaiops_home / "someone_elses.db"
    sqlite3.connect(store).execute("CREATE TABLE accounts (x)").connection.close()
    before = store.read_bytes()
    out = historian_push(points=[{"ref": "a", "value": 1}], sink="sqlite", database=str(store))
    assert "error" in out, out
    assert store.read_bytes() == before


def test_historian_push_into_the_local_sample_store_still_works(isolated_iaiops_home):
    """data.db IS the sample store: pushing samples into it is the tool's job."""
    from iaiops.core.sink.sqlite_local import local_db_path
    from mcp_server.tools.compliance_tools import historian_push

    out = historian_push(
        points=[{"ref": "b", "value": 2}], sink="sqlite", database=str(local_db_path())
    )
    assert out.get("written") == 1, out
