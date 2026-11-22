"""Readiness cannot turn missing/invalid evidence into a definite diagnosis."""

import copy
import hashlib
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from iaiops.cli._root import app
from iaiops.core.governance.audit import get_engine
from iaiops.core.readiness.diagnostic import assess_diagnostic, timestamp
from iaiops.core.readiness.diagnostic_export import export_diagnostic_bundle, render_card

FIXTURES = Path(__file__).resolve().parents[1] / "demo/sandbox-readiness"


@pytest.fixture
def sufficient():
    return json.loads((FIXTURES / "sufficient.json").read_text())


def assess(data, **kwargs):
    return assess_diagnostic(data, now=timestamp(data["window"]["end"]), **kwargs)


def test_sufficient_bounded_stop(sufficient):
    result = assess(sufficient)
    assert result["live_readiness"]
    measured = result["diagnostic"]["measurement"]
    assert measured["stops"] == 1
    assert measured["stopped_s"] == 6
    assert result["diagnostic"]["root_cause"] is None


def test_fixture_missing_critical_samples():
    result = assess(json.loads((FIXTURES / "insufficient.json").read_text()))
    assert result["configuration"]["status"] == "ready"
    assert result["status"] == "insufficient_evidence"
    assert result["diagnostic"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "mapping",
        "missing",
        "quality",
        "historical",
        "invalid",
        "unknown",
        "duplicate",
        "reversed",
        "outside",
        "naive",
        "wrong_endpoint",
        "wrong_ref",
        "gap",
    ],
)
def test_unsafe_evidence_withholds_diagnostic(sufficient, mutation):
    data = copy.deepcopy(sufficient)
    rows = data["samples"]
    if mutation == "mapping":
        del data["mapping"]["running_when"]
    elif mutation == "missing":
        data["samples"] = []
    elif mutation in ("quality", "historical", "wrong_endpoint", "wrong_ref"):
        key, value = {
            "quality": ("quality", "bad"),
            "historical": ("historical", True),
            "wrong_endpoint": ("endpoint", "other"),
            "wrong_ref": ("ref", "other"),
        }[mutation]
        rows[5][key] = value
    elif mutation in ("invalid", "unknown"):
        rows[5]["value"] = float("nan") if mutation == "invalid" else 9
    elif mutation == "duplicate":
        rows[5]["ts"] = rows[4]["ts"]
    elif mutation == "reversed":
        data["samples"] = rows[::-1]
    elif mutation == "outside":
        rows[5]["ts"] = "2020-01-01T00:00:00Z"
    elif mutation == "naive":
        rows[5]["ts"] = "2026-11-21T00:00:05"
    elif mutation == "gap":
        data["samples"] = rows[:5] + rows[10:]
    result = assess(data)
    assert result["status"] != "ready"
    assert result["diagnostic"] is None


def test_replay_is_not_live_and_future_clock_rejected(sufficient):
    end = timestamp(sufficient["window"]["end"])
    stale = assess_diagnostic(sufficient, now=end + timedelta(days=1))
    assert stale["status"] == "insufficient_evidence"
    replay = assess_diagnostic(sufficient, now=end + timedelta(days=1), replay=True)
    assert replay["status"] == "ready" and not replay["live_readiness"]
    future = assess_diagnostic(sufficient, now=end - timedelta(seconds=1), replay=True)
    assert future["diagnostic"] is None


@pytest.mark.parametrize("key", ["window", "policy", "mapping", "samples"])
def test_malformed_contract_is_teaching_error(sufficient, key):
    sufficient[key] = 7
    with pytest.raises(ValueError):
        assess_diagnostic(sufficient, now=timestamp("2026-11-22T00:00:00Z"))


def test_bundle_exact_hashes_missing_provenance_and_no_overwrite(tmp_path, sufficient):
    out = tmp_path / "evidence.zip"
    raw = json.dumps(sufficient).encode()
    report = assess(sufficient)
    export_diagnostic_bundle(out, raw=raw, report=report, identity={}, audit=[])
    original = out.read_bytes()
    with zipfile.ZipFile(out) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert set(z.namelist()) == set(manifest["files"]) | {"manifest.json"}
        for name, info in manifest["files"].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == info["sha256"]
        assert z.read("input.json") == raw
        assert (
            json.loads(z.read("identity.json"))["runtime_image_digest"]["verification"] == "missing"
        )
    with pytest.raises(FileExistsError):
        export_diagnostic_bundle(out, raw=raw, report=report, identity={}, audit=[])
    assert out.read_bytes() == original


def test_html_inert(sufficient):
    report = assess(sufficient)
    report["evidence"]["gaps"] = ['<script>alert("x")</script>']
    page = render_card(report).decode()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "Content-Security-Policy" in page


@pytest.mark.parametrize(
    "case,code,status", [("sufficient", 0, "ready"), ("insufficient", 2, "insufficient_evidence")]
)
def test_governed_cli_exports_both_outcomes(tmp_path, case, code, status):
    out = tmp_path / f"{case}.zip"
    result = CliRunner().invoke(
        app,
        [
            "diagnostic-card",
            "--input",
            str(FIXTURES / f"{case}.json"),
            "--out",
            str(out),
            "--replay",
        ],
    )
    assert result.exit_code == code, result.output
    with zipfile.ZipFile(out) as z:
        report = json.loads(z.read("assessment.json"))
        audit = json.loads(z.read("audit-reference.json"))
        assert report["status"] == status
        assert audit[0]["workflow_id"] == report["audit_reference"]["workflow_id"]
        assert audit[0]["tool"] == "diagnostic_card_assessment"
    assert get_engine().query(tool="diagnostic_card_cmd")


def test_identity_refuses_credentials_before_export(tmp_path):
    identity = tmp_path / "identity.json"
    identity.write_text('{"password":"never export"}')
    out = tmp_path / "no.zip"
    result = CliRunner().invoke(
        app,
        [
            "diagnostic-card",
            "--input",
            str(FIXTURES / "sufficient.json"),
            "--out",
            str(out),
            "--identity",
            str(identity),
            "--replay",
        ],
    )
    assert result.exit_code == 1 and not out.exists()
    assert "never export" not in result.output


def test_huge_numeric_value_is_insufficient(sufficient):
    sufficient["samples"][5]["value"] = 10**1000
    assert assess(sufficient)["diagnostic"] is None


def test_stale_last_sample_even_when_window_current(sufficient):
    sufficient["policy"]["max_age_s"] = 0.5
    sufficient["samples"].pop()
    result = assess(sufficient)
    assert result["diagnostic"] is None
    assert any("stale" in gap for gap in result["evidence"]["gaps"])


def test_audit_failure_refuses_export(tmp_path, monkeypatch):
    monkeypatch.setattr(get_engine(), "log", lambda **kw: False)
    out = tmp_path / "absent.zip"
    result = CliRunner().invoke(
        app,
        [
            "diagnostic-card",
            "--input",
            str(FIXTURES / "sufficient.json"),
            "--out",
            str(out),
            "--replay",
        ],
    )
    assert result.exit_code == 1 and not out.exists()


def test_policy_denial_precedes_read_and_export(tmp_path, monkeypatch):
    from iaiops.core.governance.policy import PolicyResult
    from iaiops.core.governance.policy import get_policy_engine as get_policy

    def deny(*args, **kwargs):
        return PolicyResult(allowed=False, reason="readiness denied for test")

    monkeypatch.setattr(get_policy(), "check_allowed", deny)
    out = tmp_path / "absent.zip"
    result = CliRunner().invoke(
        app,
        [
            "diagnostic-card",
            "--input",
            str(tmp_path / "nonexistent.json"),
            "--out",
            str(out),
            "--replay",
        ],
    )
    assert result.exit_code == 1 and not out.exists()
    assert "Denied" in result.output
