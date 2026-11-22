"""Governed offline PdM evaluation and explicit case/maintenance linkage."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors
from iaiops.cli.diagnostic_card import _read
from iaiops.core.evaluation.bundle import export_bundle, read_evaluation
from iaiops.core.evaluation.feedback import feedback_contract, observation
from iaiops.core.evaluation.pdm import evaluate
from iaiops.core.readiness.diagnostic import timestamp
from iaiops.core.readiness.diagnostic_export import json_bytes

pdm_evaluation_app = typer.Typer(help="Offline frozen-threshold PdM evaluation and feedback.")


def _audit(kind: str, raw: bytes) -> bytes:
    from iaiops.core.governance.audit import get_engine

    engine = get_engine()
    workflow = str(uuid.uuid4())
    if not engine.log(
        skill="pdm_evaluation",
        tool=kind,
        workflow_id=workflow,
        params={"input_sha256": hashlib.sha256(raw).hexdigest()},
        origin="cli",
    ):
        raise ValueError("Assessment audit failed; no bundle exported")
    return json_bytes(engine.query(workflow_id=workflow))


@pdm_evaluation_app.command("run")
@cli_errors
def evaluate_cmd(
    source: Path = typer.Option(..., "--input"),
    out: Path = typer.Option(..., "--out"),
) -> None:
    """Export a reproducible evaluation. Abstentions are reported, never called healthy."""
    raw = _read(source)
    report = evaluate(json.loads(raw))
    export_bundle(
        out,
        {
            "input.json": raw,
            "evaluation.json": json_bytes(report),
            "audit-reference.json": _audit("pdm_evaluation", raw),
        },
    )
    _emit(report["metrics"])


@pdm_evaluation_app.command("open-case")
@cli_errors
def open_case_cmd(
    evaluation: Path = typer.Option(..., "--evaluation"),
    window: str = typer.Option(..., "--window"),
    site: str = typer.Option("default", "--site"),
) -> None:
    """Explicitly open an unconfirmed case bound to this alert, without ranking a cause."""
    from iaiops.core.knowledge.case_store import open_case

    report, _, _, _ = read_evaluation(evaluation)
    row = observation(report, window)
    if row["alert"] is not True:
        raise ValueError("Only a scored alert opens this reference case")
    case = open_case(site, row["asset"], row["start"], evidence_ref=row["diagnosis_id"])
    _emit(
        {
            "case_id": case.incident_id,
            "diagnosis_id": case.evidence_ref,
            "label": case.label,
            "next": "Use existing iaiops case confirm/dismiss explicitly.",
        }
    )


@pdm_evaluation_app.command("feedback")
@cli_errors
def feedback_cmd(
    evaluation: Path = typer.Option(..., "--evaluation"),
    window: str = typer.Option(..., "--window"),
    source: Path = typer.Option(..., "--input"),
    out: Path = typer.Option(..., "--out"),
    site: str = typer.Option("default", "--site"),
) -> None:
    """Snapshot existing human confirmation plus maintenance; never train or tune."""
    from iaiops.core.knowledge.case_store import case_id, list_cases

    report, original, assessed, evaluation_audit = read_evaluation(evaluation)
    row = observation(report, window)
    cases = [c for c in list_cases(site) if c.incident_id == case_id(row["asset"], row["start"])]
    if len(cases) != 1:
        raise ValueError("Open the exact PdM case before exporting feedback")
    raw = _read(source)
    contract = feedback_contract(report, window, json.loads(raw), cases[0])
    from iaiops.core.governance.audit import get_engine

    tool = "case_confirm_cmd" if cases[0].label else "case_dismiss_cmd"
    candidates = get_engine().query(tool=tool, status="ok", limit=1000)
    matched = []
    for candidate in candidates:
        try:
            params = json.loads(candidate["params"])
            if not isinstance(params, dict):
                continue
        except (ValueError, TypeError):
            continue
        try:
            current_answer = bool(cases[0].answered_at) and (
                timestamp(candidate["ts"]) >= timestamp(cases[0].answered_at)
            )
        except (ValueError, KeyError):
            current_answer = False
        if (
            current_answer
            and params.get("incident_id") == cases[0].incident_id
            and params.get("site") == site
            and params.get("by") == cases[0].answered_by
            and (not cases[0].label or params.get("cause") == cases[0].label)
        ):
            matched.append(candidate)
    confirmation_reference = {
        "status": "matching_records" if matched else "not_found_within_bound",
        "lookup_limit": 1000,
        "possibly_truncated": len(candidates) == 1000,
        "scope": "matching local CLI declarations, not authenticated human identity/full chain",
        "rows": matched,
    }
    export_bundle(
        out,
        {
            "input.json": original,
            "evaluation.json": assessed,
            "evaluation-audit-reference.json": evaluation_audit,
            "case-confirmation-reference.json": json_bytes(confirmation_reference),
            "feedback-request.json": raw,
            "feedback.json": json_bytes(contract),
            "audit-reference.json": _audit("pdm_feedback", raw),
        },
    )
    _emit({"outcome": contract["outcome"], "case_id": contract["case_id"], "updates_applied": []})
