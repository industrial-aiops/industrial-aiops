"""Evidence-bundle export tests (A3): zip contents, chain-verify result,
since/until window, path validation (traversal / suffix / ISO), and the
governed MCP tool."""

from __future__ import annotations

import json
import stat
import zipfile

import pytest

from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.evidence import (
    AUDIT_ROWS_NAME,
    CHAIN_VERIFICATION_NAME,
    DOCTOR_SUMMARY_NAME,
    MANIFEST_NAME,
    RULES_NAME,
    export_evidence_bundle,
    validate_output_path,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    reset_engine()
    yield
    reset_engine()


def _seed(n: int) -> None:
    engine = get_engine()
    for i in range(n):
        assert engine.log(skill="iaiops", tool=f"tool_{i}", params={"i": i}, status="ok")


# ─── bundle contents ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_bundle_contains_all_evidence(tmp_path):
    _seed(4)
    rules = tmp_path / "rules.yaml"  # IAIOPS_HOME/rules.yaml
    rules.write_text("risk_tiers: []\n", encoding="utf-8")

    out = export_evidence_bundle(tmp_path / "bundle.zip")
    assert out["row_count"] == 4
    assert out["chain"]["ok"] is True

    with zipfile.ZipFile(out["path"]) as bundle:
        names = set(bundle.namelist())
        assert names == {AUDIT_ROWS_NAME, CHAIN_VERIFICATION_NAME, RULES_NAME,
                         DOCTOR_SUMMARY_NAME, MANIFEST_NAME}
        rows = [json.loads(line) for line in
                bundle.read(AUDIT_ROWS_NAME).decode().splitlines()]
        assert len(rows) == 4
        assert all(r["row_hash"] and "ts" in r for r in rows)
        chain = json.loads(bundle.read(CHAIN_VERIFICATION_NAME))
        assert chain == {"ok": True, "checked": 4, "unhashed": 0}
        assert bundle.read(RULES_NAME).decode() == "risk_tiers: []\n"
        doctor = json.loads(bundle.read(DOCTOR_SUMMARY_NAME))
        assert "iaiops_version" in doctor and "generated_at" in doctor
        manifest = json.loads(bundle.read(MANIFEST_NAME))
        assert manifest["row_count"] == 4 and manifest["chain_ok"] is True
        assert manifest["rules_yaml_included"] is True


@pytest.mark.unit
def test_bundle_without_rules_yaml(tmp_path):
    _seed(1)
    out = export_evidence_bundle(tmp_path / "bundle.zip")
    with zipfile.ZipFile(out["path"]) as bundle:
        assert RULES_NAME not in bundle.namelist()
    assert RULES_NAME not in out["files"]


@pytest.mark.unit
def test_bundle_since_until_window(tmp_path):
    _seed(3)
    engine = get_engine()
    all_rows = engine.rows_after(0)
    middle_ts = all_rows[1]["ts"]
    out = export_evidence_bundle(
        tmp_path / "windowed.zip", since=middle_ts, until=middle_ts
    )
    assert out["row_count"] == 1
    with zipfile.ZipFile(out["path"]) as bundle:
        rows = bundle.read(AUDIT_ROWS_NAME).decode().splitlines()
        assert json.loads(rows[0])["ts"] == middle_ts


@pytest.mark.unit
def test_bundle_creates_parent_dir_0700(tmp_path):
    _seed(1)
    nested = tmp_path / "new" / "dir" / "bundle.zip"
    out = export_evidence_bundle(nested)
    assert nested.exists()
    mode = stat.S_IMODE(nested.parent.stat().st_mode)
    assert mode == 0o700
    assert stat.S_IMODE(nested.stat().st_mode) == 0o600
    assert out["path"] == str(nested)


# ─── validation ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_bundle_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="traversal"):
        export_evidence_bundle(tmp_path / ".." / "evil.zip")


@pytest.mark.unit
def test_bundle_rejects_wrong_suffix(tmp_path):
    with pytest.raises(ValueError, match="must end in"):
        export_evidence_bundle(tmp_path / "bundle.tar")


@pytest.mark.unit
def test_bundle_rejects_bad_iso_bounds(tmp_path):
    with pytest.raises(ValueError, match="ISO-8601"):
        export_evidence_bundle(tmp_path / "b.zip", since="yesterday")
    with pytest.raises(ValueError, match="ISO-8601"):
        export_evidence_bundle(tmp_path / "b.zip", until="not-a-date")
    with pytest.raises(ValueError, match="after"):
        export_evidence_bundle(
            tmp_path / "b.zip", since="2026-07-02", until="2026-07-01"
        )


@pytest.mark.unit
def test_validate_output_path_rejects_directory(tmp_path):
    with pytest.raises(ValueError, match="directory"):
        target = tmp_path / "a.zip"
        target.mkdir()
        validate_output_path(target, suffixes=(".zip",))


# ─── Governed MCP tool ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_mcp_evidence_bundle_tool(tmp_path):
    _seed(2)
    from mcp_server.tools.compliance_tools import compliance_evidence_bundle

    assert getattr(compliance_evidence_bundle, "_is_governed_tool", False) is True
    out = compliance_evidence_bundle(out_path=str(tmp_path / "mcp.zip"))
    assert "error" not in out
    # The tool call itself is audited AFTER the export; the seeded 2 rows are in.
    assert out["row_count"] >= 2
    assert out["chain"]["ok"] is True


@pytest.mark.unit
def test_mcp_evidence_bundle_rejects_traversal(tmp_path):
    from mcp_server.tools.compliance_tools import compliance_evidence_bundle

    out = compliance_evidence_bundle(out_path=str(tmp_path / ".." / "evil.zip"))
    assert "error" in out
