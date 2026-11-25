"""Portable local reproduction bundle, not organization-level attestation."""

from __future__ import annotations

import hashlib
import html
import json
import os
import zipfile
from pathlib import Path

from iaiops import __version__
from iaiops.core.governance.evidence import validate_output_path

IDENTITY_KEYS = (
    "application_package_digest",
    "compose_component_digest",
    "runtime_image_digest",
    "deployment_id",
    "platform_version",
    "source_revision",
)


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def identity_inventory(identity: dict) -> dict:
    if not isinstance(identity, dict) or set(identity) - set(IDENTITY_KEYS):
        raise ValueError(
            "Identity must contain only the documented provenance fields; never credentials"
        )
    result = {}
    for key in IDENTITY_KEYS:
        value = identity.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 512):
            raise ValueError(f"Invalid identity field: {key}")
        result[key] = {
            "value": value or None,
            "verification": "operator_supplied" if value else "missing",
        }
    return result


def render_card(report: dict) -> bytes:
    """Self-contained inert HTML; input text cannot become markup or script."""
    esc = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    gaps = report["configuration"]["gaps"] + report["evidence"]["gaps"]
    detail = (
        "".join(f"<li>{esc(g)}</li>" for g in gaps) or "<li>Required evidence checks passed.</li>"
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>IAIops diagnostic readiness</title><style>"
        "body{font:17px system-ui;max-width:900px;margin:40px auto;padding:0 20px;color:#183040}"
        "section{border:1px solid #aac;padding:20px;border-radius:12px}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        "</style><h1>Diagnostic readiness / 诊断就绪卡</h1><section>"
        f"<h2>{esc(report['status'])}</h2><p>Mode: {esc(report['mode'])}</p>"
        f"<p>Snapshot generated: {esc(report['generated_at'])}</p>"
        f"<p>Valid until: {esc(report['valid_until'])} (replay has no live validity).</p>"
        "<p>This is a saved assessment, not continuous monitoring. Reassess after expiry.</p>"
        f"<p>Configuration: {esc(report['configuration']['status'])} · "
        f"Evidence: {esc(report['evidence']['status'])}</p>"
        f"<p>Window: {esc(report['window']['start'])} → {esc(report['window']['end'])}</p>"
        f"<ul>{detail}</ul></section><h2>Bounded observation</h2>"
        f"<pre>{esc(json_bytes(report['diagnostic']).decode())}</pre>"
        "<h2>Scope and limitations</h2><ul>"
        + "".join(f"<li>{esc(v)}</li>" for v in report["limitations"])
        + "</ul><h2>Deployment identity (operator supplied / missing)</h2><pre>"
        + esc(json_bytes(report.get("identity", {})).decode())
        + "</pre></html>"
    ).encode()


def export_diagnostic_bundle(
    out: Path, *, raw: bytes, report: dict, identity: dict, audit: list[dict]
) -> dict:
    """Fixed archive names; hashes cover exact bytes including raw source input.

    The manifest is an unsigned integrity inventory, not independent proof of
    origin. Audit rows are only this assessment's references, not the whole chain.
    """
    entries = {
        "input.json": raw,
        "assessment.json": json_bytes(report),
        "identity.json": json_bytes(identity_inventory(identity)),
        "audit-reference.json": json_bytes(audit),
        "card.html": render_card(report),
    }
    manifest = {
        "schema": "iaiops.diagnostic-evidence/v1",
        "package_version": __version__,
        "attestation": "unsigned local inventory; identity not independently verified",
        "files": {
            name: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            for name, body in entries.items()
        },
    }
    target = validate_output_path(out, suffixes=(".zip",))
    # Exclusive creation prevents accidental destruction of earlier evidence.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in entries.items():
                archive.writestr(name, body)
            archive.writestr("manifest.json", json_bytes(manifest))
    return {"bundle": str(target), "manifest": manifest}
