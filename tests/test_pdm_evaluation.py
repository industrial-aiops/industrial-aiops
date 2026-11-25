"""Pinned metrics and explicit human confirmation, not inference from predictions."""

import copy
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from iaiops.cli._root import app
from iaiops.core.evaluation.bundle import read_evaluation
from iaiops.core.evaluation.feedback import feedback_contract
from iaiops.core.evaluation.pdm import evaluate
from iaiops.core.knowledge.case_store import confirm_case, dismiss_case, list_cases, open_case

DATA = Path(__file__).resolve().parents[1] / "demo/pdm-feedback/dataset.json"


@pytest.fixture
def data():
    return json.loads(DATA.read_text())


def test_metrics_include_abstention_without_crediting_it_healthy(data):
    result = evaluate(data)
    m = result["metrics"]
    assert [m[k] for k in ("tp", "fp", "tn", "fn", "abstained")] == [1, 1, 1, 1, 1]
    assert m["coverage"] == 0.8 and m["event_recall"] == 1 / 3
    assert m["false_alarms_per_scored_hour"] == 0.5
    assert m["mean_matched_lead_s"] == 600 and m["threshold_eta_mae_s"] == 0
    assert m["lifetime_interval_coverage"] is None
    assert result["windows"][-1]["forecast"] is None


@pytest.mark.parametrize(
    "kind",
    [
        "asset_leak",
        "source_leak",
        "duplicate_id",
        "overlap",
        "duplicate_event",
        "followup",
        "future_sample",
        "nan",
        "quality",
        "missing_time",
        "order",
        "already_crossed",
    ],
)
def test_invalid_or_leaky_evidence(data, kind):
    w = data["windows"][0]
    structural = True
    if kind == "asset_leak":
        w["asset"] = data["reference_groups"][0]["asset"]
    elif kind == "source_leak":
        w["source_group"] = data["reference_groups"][0]["source_group"]
    elif kind == "duplicate_id":
        data["windows"][1]["id"] = w["id"]
    elif kind == "overlap":
        data["windows"][1]["asset"] = w["asset"]
    elif kind == "duplicate_event":
        data["windows"][-1]["label"]["event_id"] = w["label"]["event_id"]
    elif kind == "followup":
        w["label"]["observed_until"] = w["end"]
    else:
        structural = False
        if kind == "future_sample":
            w["samples"][0]["ts"] = "2027-01-01T00:00:00Z"
        elif kind == "nan":
            w["samples"][0]["value"] = "NaN"
        elif kind == "quality":
            w["samples"][0]["quality"] = "bad"
        elif kind == "missing_time":
            del w["samples"][0]["ts"]
        elif kind == "order":
            w["samples"].reverse()
        elif kind == "already_crossed":
            w["samples"][-1]["value"] = 41
    if structural:
        with pytest.raises(ValueError):
            evaluate(data)
    else:
        result = evaluate(data)["windows"][0]
        assert result["forecast"] is None and result["alert"] is None


def test_labels_never_enter_forecast(data):
    before = evaluate(data)["windows"][0]["forecast"]
    data["windows"][0]["label"] = copy.deepcopy(data["windows"][1]["label"])
    assert evaluate(data)["windows"][0]["forecast"] == before


def bound_case(report, tmp_path):
    row = report["windows"][0]
    return open_case(
        "test", row["asset"], row["start"], base_dir=tmp_path, evidence_ref=row["diagnosis_id"]
    )


def test_feedback_requires_existing_confirmation_and_explicit_maintenance(data, tmp_path):
    report = evaluate(data)
    case = bound_case(report, tmp_path)
    request = {
        "schema": "iaiops.pdm-feedback-request/v1",
        "outcome": "pending",
        "by": "fixture reviewer",
    }
    pending = feedback_contract(report, "detected", request, case)
    assert not pending["case"]["value"]["label"]
    request["outcome"] = "confirmed"
    with pytest.raises(ValueError, match="case confirm"):
        feedback_contract(report, "detected", request, case)
    case = confirm_case(
        "test", case.incident_id, "mechanical_fault", "fixture reviewer", base_dir=tmp_path
    )
    assert list_cases("test", base_dir=tmp_path)[0].evidence_ref == case.evidence_ref
    request["maintenance"] = {
        "work_order_id": "synthetic-wo",
        "device_id": case.endpoint,
        "case_id": case.incident_id,
        "diagnosis_id": case.evidence_ref,
        "cause": "mechanical_fault",
        "completed_at": "2026-11-20T02:00:00Z",
    }
    result = feedback_contract(report, "detected", request, case)
    assert result["maintenance_bridge"]["corpus"][0]["cause"] == "mechanical_fault"
    assert "weights" not in result["maintenance_bridge"] and result["updates_applied"] == []
    request["maintenance"]["cause"] = "sensor_fault"
    with pytest.raises(ValueError, match="conflicts"):
        feedback_contract(report, "detected", request, case)


def test_binding_conflicts_and_dismissal_preserve_provenance(data, tmp_path):
    report = evaluate(data)
    case = bound_case(report, tmp_path)
    row = report["windows"][0]
    with pytest.raises(ValueError, match="binding conflict"):
        open_case("test", row["asset"], row["start"], base_dir=tmp_path, evidence_ref="different")
    case = dismiss_case("test", case.incident_id, "reviewer", base_dir=tmp_path)
    request = {
        "schema": "iaiops.pdm-feedback-request/v1",
        "outcome": "false_positive",
        "by": "reviewer",
    }
    assert feedback_contract(report, "detected", request, case)["outcome"] == "false_positive"
    report["windows"][0]["diagnosis_id"] = "changed"
    with pytest.raises(ValueError):
        feedback_contract(report, "detected", request, case)


def test_governed_cli_and_tampered_archive(tmp_path):
    out = tmp_path / "evaluation.zip"
    runner = CliRunner()
    result = runner.invoke(app, ["pdm-evaluation", "run", "--input", str(DATA), "--out", str(out)])
    assert result.exit_code == 0, result.output
    report, _, _, _ = read_evaluation(out)
    result = runner.invoke(
        app, ["pdm-evaluation", "open-case", "--evaluation", str(out), "--window", "detected"]
    )
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    entries["evaluation.json"] = b"{}"
    bad = tmp_path / "tampered.zip"
    with zipfile.ZipFile(bad, "w") as z:
        for n, b in entries.items():
            z.writestr(n, b)
    with pytest.raises(ValueError, match="hash mismatch"):
        read_evaluation(bad)
    result = runner.invoke(app, ["pdm-evaluation", "run", "--input", str(DATA), "--out", str(out)])
    assert result.exit_code == 1


@pytest.mark.parametrize("key,value", [("unit", "C"), ("condition", "different load")])
def test_wrong_policy_applicability(data, key, value):
    data["windows"][0][key] = value
    with pytest.raises(ValueError, match="applicability"):
        evaluate(data)


def test_all_abstained_metrics_are_not_zero_accuracy(data):
    for w in data["windows"]:
        w["samples"] = []
    m = evaluate(data)["metrics"]
    assert m["event_recall"] == 0 and m["tn"] == 0 and m["unscored_events"] == 3
    assert m["precision"] is None and m["false_alarms_per_scored_hour"] is None
    assert m["coverage"] == 0 and m["scored_time_coverage"] == 0


def test_nonfinite_json_is_invalid_contract(data):
    data["windows"][0]["samples"][0]["value"] = float("nan")
    with pytest.raises(ValueError):
        evaluate(data)


def test_inconclusive_does_not_invent_label(data, tmp_path):
    report = evaluate(data)
    case = bound_case(report, tmp_path)
    request = {
        "schema": "iaiops.pdm-feedback-request/v1",
        "outcome": "inconclusive",
        "by": "reviewer",
    }
    f = feedback_contract(report, "detected", request, case)
    assert f["case"]["value"]["label"] == "" and f["maintenance_bridge"] is None
    request["outcome"] = "false_positive"
    with pytest.raises(ValueError, match="dismiss"):
        feedback_contract(report, "detected", request, case)


def test_policy_denial_prevents_export(tmp_path, monkeypatch):
    from iaiops.core.governance.policy import PolicyResult, get_policy_engine

    monkeypatch.setattr(
        get_policy_engine(), "check_allowed", lambda *a, **k: PolicyResult(False, reason="denied")
    )
    out = tmp_path / "none.zip"
    r = CliRunner().invoke(app, ["pdm-evaluation", "run", "--input", str(DATA), "--out", str(out)])
    assert r.exit_code == 1 and not out.exists() and "Denied" in r.output


def test_audit_failure_prevents_export(tmp_path, monkeypatch):
    from iaiops.core.governance.audit import get_engine

    monkeypatch.setattr(get_engine(), "log", lambda **k: False)
    out = tmp_path / "none.zip"
    r = CliRunner().invoke(app, ["pdm-evaluation", "run", "--input", str(DATA), "--out", str(out)])
    assert r.exit_code == 1 and not out.exists()


def test_truth_revision_changes_dataset_not_prediction_identity(data):
    original = evaluate(data)
    data["windows"][0]["label"] = copy.deepcopy(data["windows"][1]["label"])
    revised = evaluate(data)
    assert original["dataset_digest"] != revised["dataset_digest"]
    assert original["windows"][0]["diagnosis_id"] == revised["windows"][0]["diagnosis_id"]
    data["policy"]["revision"] = "new-threshold-review"
    assert evaluate(data)["windows"][0]["diagnosis_id"] != revised["windows"][0]["diagnosis_id"]
