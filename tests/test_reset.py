"""`iaiops reset` — remove all local data and settings (CRA Annex I Part I(2)(b)(m)).

The command deletes what iaiops itself wrote: config, encrypted secrets, the
audit trail and its archives, undo and approval state, collected history. The
tests pin the parts that must not be flattering: the preview changes nothing,
symlinks are never followed out of the roots, a root that is not an iaiops home
is refused, external stores are named as not covered, the trail restarts with
the reset's own record, and nothing claims a secure erase it cannot perform.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iaiops.core.runtime import reset as reset_mod

pytestmark = pytest.mark.unit


def _point_config_roots(monkeypatch, directory: Path) -> None:
    from iaiops.core.runtime import config, secretstore

    monkeypatch.setattr(config, "CONFIG_DIR", directory)
    monkeypatch.setattr(secretstore, "CONFIG_DIR", directory)


@pytest.fixture
def homes(tmp_path, monkeypatch):
    home = tmp_path / "ops"
    cfg = tmp_path / "cfg" / ".iaiops"
    home.mkdir()
    cfg.mkdir(parents=True)
    from iaiops.core.governance.audit import AuditEngine, reset_engine

    AuditEngine(home / "audit.db")  # a real trail, so governance is healthy
    (home / "audit.db.20260101.archive").write_text("x")
    (home / "approvals").mkdir()
    (home / "approvals" / "tok.json").write_text("{}")
    (home / "data.db").write_text("rows")
    (cfg / "config.yaml").write_text("endpoints: []\n")
    (cfg / "secrets.enc").write_text("ciphertext")
    monkeypatch.setenv("IAIOPS_HOME", str(home))
    _point_config_roots(monkeypatch, cfg)
    monkeypatch.delenv("IAIOPS_CONFIG", raising=False)
    reset_engine()
    yield home, cfg
    reset_engine()


def test_the_plan_lists_everything_and_changes_nothing(homes):
    home, cfg = homes
    plan = reset_mod.plan_reset()
    paths = {Path(e["path"]) for e in plan["entries"]}
    assert home / "audit.db" in paths and home / "approvals" in paths
    assert cfg / "secrets.enc" in paths and cfg / "config.yaml" in paths
    assert (home / "audit.db").exists() and (cfg / "secrets.enc").exists()


def test_the_plan_names_what_it_does_not_cover(homes):
    plan = reset_mod.plan_reset()
    text = " ".join(plan["not_covered"]).lower()
    assert "tdengine" in text and "iotdb" in text
    assert "not shredded" in plan["erase_note"].lower()


def test_apply_removes_everything_and_restarts_the_trail(homes):
    home, cfg = homes
    result = reset_mod.apply_reset(reset_mod.plan_reset())
    assert result["errors"] == []
    assert not (cfg / "secrets.enc").exists() and not (cfg / "config.yaml").exists()
    assert not (home / "approvals").exists() and not (home / "data.db").exists()
    assert not (home / "audit.db.20260101.archive").exists()
    # A fresh, EMPTY trail exists so the reset's own audit row has somewhere to go.
    assert (home / "audit.db").exists()
    from iaiops.core.governance.audit import AuditEngine

    assert AuditEngine(home / "audit.db").query(limit=10) == []


def test_symlinks_are_removed_not_followed(homes, tmp_path):
    home, _ = homes
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (home / "link").symlink_to(outside, target_is_directory=True)
    reset_mod.apply_reset(reset_mod.plan_reset())
    assert not (home / "link").exists()
    assert (outside / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("bad", ["/", "HOME"])
def test_a_root_that_is_not_an_iaiops_home_is_refused(monkeypatch, bad, tmp_path):
    target = str(Path.home()) if bad == "HOME" else bad
    monkeypatch.setenv("IAIOPS_HOME", target)
    _point_config_roots(monkeypatch, tmp_path / ".iaiops")
    with pytest.raises(ValueError, match="(?i)refus"):
        reset_mod.plan_reset()


def test_a_config_override_outside_the_roots_is_included(homes, tmp_path, monkeypatch):
    elsewhere = tmp_path / "site" / "plant.yaml"
    elsewhere.parent.mkdir()
    elsewhere.write_text("endpoints: []\n")
    monkeypatch.setenv("IAIOPS_CONFIG", str(elsewhere))
    plan = reset_mod.plan_reset()
    assert str(elsewhere) in {e["path"] for e in plan["entries"]}
    reset_mod.apply_reset(plan)
    assert not elsewhere.exists()
    assert elsewhere.parent.exists(), "only the file, never the directory it sits in"


def test_a_failed_removal_is_reported_not_swallowed(homes, monkeypatch):
    home, _ = homes

    def boom(_path):
        raise PermissionError("read-only volume")

    monkeypatch.setattr(reset_mod, "_remove", boom)
    result = reset_mod.apply_reset(reset_mod.plan_reset())
    assert result["errors"], "a removal that failed was reported as done"
    assert "read-only volume" in result["errors"][0]["error"]


def test_missing_roots_are_fine(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path / "nothing-here" / ".iaiops"))
    _point_config_roots(monkeypatch, tmp_path / "none" / ".iaiops")
    monkeypatch.delenv("IAIOPS_CONFIG", raising=False)
    assert reset_mod.plan_reset()["entries"] == []


# ─── the CLI front ───────────────────────────────────────────────────────────


def test_cli_preview_changes_nothing(homes):
    from typer.testing import CliRunner

    from iaiops.cli._root import app

    home, cfg = homes
    result = CliRunner().invoke(app, ["reset"])
    assert result.exit_code == 0, result.output
    assert "secrets.enc" in result.output
    assert (cfg / "secrets.enc").exists() and (home / "data.db").exists()


def test_cli_apply_without_an_approver_is_denied(homes):
    """Wiping the audit trail is a high-risk change: MOC applies, like a device write."""
    from typer.testing import CliRunner

    from iaiops.cli._root import app

    _, cfg = homes
    result = CliRunner().invoke(app, ["reset", "--apply"], input="y\ny\n")
    assert result.exit_code != 0
    assert (cfg / "secrets.enc").exists()


def test_cli_apply_with_approval_and_confirmation_resets(homes):
    from typer.testing import CliRunner

    from iaiops.cli._root import app
    from iaiops.core.governance.approvals import record_approval
    from iaiops.core.governance.audit import AuditEngine

    home, cfg = homes
    record_approval("reset_cmd", approved_by="site-admin")
    result = CliRunner().invoke(app, ["reset", "--apply"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert not (cfg / "secrets.enc").exists()
    rows = AuditEngine(home / "audit.db").query(limit=10)
    assert [r["tool"] for r in rows] == ["reset_cmd"], "the new trail starts with the reset"
    assert rows[0]["approved_by"] == "site-admin"
