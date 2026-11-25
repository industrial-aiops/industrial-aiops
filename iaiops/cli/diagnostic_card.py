"""Audited, offline single-window diagnostic card and reproduction export."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors


def _read(path: Path) -> bytes:
    with path.expanduser().open("rb") as stream:
        raw = stream.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("Input exceeds the 8 MB reference-scenario limit")
    return raw


@cli_errors
def diagnostic_card_cmd(
    source: Path = typer.Option(..., "--input", help="Explicit point map and source samples JSON."),
    out: Path = typer.Option(
        ..., "--out", help="New ZIP containing card, inputs and evidence inventory."
    ),
    identity: Path | None = typer.Option(
        None, "--identity", help="Optional deployment provenance JSON, no credentials."
    ),
    replay: bool = typer.Option(
        False, "--replay", help="Historical reproduction only; never claims live readiness."
    ),
) -> None:
    """Assess supplied read-only evidence; export a portable local HTML readiness card."""
    from iaiops.core.governance.audit import get_engine
    from iaiops.core.readiness.diagnostic import assess_diagnostic
    from iaiops.core.readiness.diagnostic_export import export_diagnostic_bundle, identity_inventory

    started = time.monotonic()
    raw = _read(source)
    provenance = json.loads(_read(identity)) if identity else {}
    identity_inventory(provenance)  # validate before recording successful assessment
    report = assess_diagnostic(json.loads(raw), now=datetime.now(UTC), replay=replay)
    report["identity"] = identity_inventory(provenance)
    report["assessment_duration_ms"] = round((time.monotonic() - started) * 1000, 3)
    report["timing_scope"] = (
        "local file load + assessment; excludes installation/deployment/collection"
    )
    workflow = str(uuid.uuid4())
    engine = get_engine()
    recorded = engine.log(
        skill="readiness",
        tool="diagnostic_card_assessment",
        workflow_id=workflow,
        params={"input_sha256": hashlib.sha256(raw).hexdigest(), "replay": replay},
        result={"status": report["status"]},
        origin="cli",
        risk_level="low",
    )
    if not recorded:
        raise ValueError("Assessment audit failed; no evidence bundle exported")
    audit = engine.query(workflow_id=workflow)
    report["audit_reference"] = {
        "workflow_id": workflow,
        "scope": "assessment only; CLI export completion audited separately",
    }
    exported = export_diagnostic_bundle(
        out, raw=raw, report=report, identity=provenance, audit=audit
    )
    _emit(
        {
            "status": report["status"],
            "live_readiness": report["live_readiness"],
            "bundle": exported["bundle"],
        }
    )
    if report["status"] != "ready":
        raise typer.Exit(2)
