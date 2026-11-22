"""Pure feedback contract built from an existing case, never an inferred label."""

from __future__ import annotations

from iaiops.core.brain.maintenance_log import corpus_from_maintenance_log
from iaiops.core.evaluation.pdm import text
from iaiops.core.knowledge.case_store import case_id
from iaiops.core.readiness.diagnostic import timestamp


def observation(report: dict, window_id: str) -> dict:
    found = [w for w in report["windows"] if w["id"] == window_id]
    if len(found) != 1:
        raise ValueError("Unknown or ambiguous evaluation window")
    return found[0]


def feedback_contract(report: dict, window_id: str, request: dict, case) -> dict:
    window = observation(report, window_id)
    if window["alert"] is not True:
        raise ValueError("Feedback reference scenario requires a scored alert")
    if (
        case.incident_id != case_id(window["asset"], window["start"])
        or case.endpoint != window["asset"]
        or case.when != window["start"]
        or case.evidence_ref != window["diagnosis_id"]
    ):
        raise ValueError("Case does not bind this exact diagnosis/asset/window")
    if not isinstance(request, dict) or request.get("schema") != "iaiops.pdm-feedback-request/v1":
        raise ValueError("Expected iaiops.pdm-feedback-request/v1")
    if set(request) - {"schema", "outcome", "by", "maintenance"}:
        raise ValueError("Unknown feedback fields; case labels come only from case confirm")
    state = request.get("outcome")
    if state not in ("pending", "confirmed", "false_positive", "inconclusive"):
        raise ValueError("Unknown feedback outcome")
    if not text(request.get("by")):
        raise ValueError("Feedback requires a named declarant, not an inferred actor")
    if state == "pending" and case.answered:
        raise ValueError("An answered case cannot be exported as pending")
    if state == "confirmed" and not (case.counts_as_evidence and case.answered_by):
        raise ValueError("Use existing case confirm before confirmed feedback")
    if state == "false_positive" and not (case.answered and not case.label and case.answered_by):
        raise ValueError("Use existing case dismiss before false-positive feedback")
    record = request.get("maintenance")
    bridge = None
    if record is not None:
        if state != "confirmed" or not isinstance(record, dict):
            raise ValueError("Only confirmed feedback may link an explicit maintenance record")
        allowed = {
            "work_order_id",
            "device_id",
            "case_id",
            "diagnosis_id",
            "cause",
            "completed_at",
            "actions",
            "notes",
            "signals",
        }
        if set(record) - allowed:
            raise ValueError("Unknown maintenance fields; normalize CMMS input explicitly")
        if "actions" in record and (
            not isinstance(record["actions"], list) or any(not text(x) for x in record["actions"])
        ):
            raise ValueError("Maintenance actions must be a list of explicit statements")
        if "notes" in record and not isinstance(record["notes"], str):
            raise ValueError("Maintenance notes must be text")
        if "signals" in record:
            from iaiops.core.brain.rca_weights import LEARNABLE_CAUSES

            if not isinstance(record["signals"], list) or any(
                not isinstance(x, str) or x not in LEARNABLE_CAUSES for x in record["signals"]
            ):
                raise ValueError("Maintenance signals must use the explicit cause vocabulary")
        if not text(record.get("work_order_id")):
            raise ValueError("Maintenance needs a work_order_id")
        if (
            record.get("device_id") != window["asset"]
            or record.get("case_id") != case.incident_id
            or record.get("diagnosis_id") != window["diagnosis_id"]
            or record.get("cause") != case.label
        ):
            raise ValueError(
                "Maintenance cause/asset/case/diagnosis conflicts with confirmed evidence"
            )
        if timestamp(record.get("completed_at")) < timestamp(window["end"]):
            raise ValueError("Maintenance completion precedes the prediction window")
        bridge = corpus_from_maintenance_log([record], learn=False)
        if bridge["n_mapped"] != 1 or bridge["corpus"][0]["cause"] != case.label:
            raise ValueError("Maintenance bridge did not preserve the confirmed cause")
    return {
        "schema": "iaiops.pdm-feedback/v1",
        "dataset_digest": report["dataset_digest"],
        "diagnosis_id": window["diagnosis_id"],
        "window_id": window_id,
        "case_id": case.incident_id,
        "outcome": state,
        "declared_by": request["by"],
        "case": case.as_fact().as_dict(),
        "maintenance": record,
        "maintenance_bridge": bridge,
        "updates_applied": [],
        "note": (
            "Identities/maintenance are supplied assertions, not authenticated attestation. "
            "Feedback does not change labels, thresholds or learned weights."
        ),
    }
