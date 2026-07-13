"""Audit-evidence bundle export (A3) — everything an auditor asks for, in one zip.

``export_evidence_bundle`` packages the governance evidence trail into a single
deterministic zip: audit rows (JSON lines — secrets are already redacted upstream
by the governed-tool decorator), the hash-chain verification result (reusing
``AuditEngine.verify_chain``), the current ``rules.yaml`` (if present), a
non-probing doctor summary, and a manifest. Output paths are validated (no
``..`` traversal) and parent directories are created ``0700``.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops import __version__ as _iaiops_version
from iaiops.core.governance.audit import get_engine
from iaiops.core.governance.paths import ops_path

# Deterministic file names inside the bundle.
AUDIT_ROWS_NAME = "audit_rows.jsonl"
CHAIN_VERIFICATION_NAME = "chain_verification.json"
RULES_NAME = "rules.yaml"
DOCTOR_SUMMARY_NAME = "doctor_summary.json"
MANIFEST_NAME = "manifest.json"

_PAGE_SIZE = 1000
_MAX_ROWS = 500_000  # hard ceiling so a runaway DB cannot exhaust memory


def validate_output_path(out_path: str | Path, *, suffixes: tuple[str, ...]) -> Path:
    """Validate a user-supplied output file path and prepare its directory.

    Rejects traversal (``..`` segments) and wrong extensions; creates the
    parent directory ``0700`` when missing. Returns the expanded Path.
    """
    path = Path(out_path).expanduser()
    if ".." in path.parts:
        raise ValueError(f"Refusing output path with '..' traversal: {out_path}")
    if path.suffix.lower() not in suffixes:
        allowed = "/".join(suffixes)
        raise ValueError(f"Output path must end in {allowed}, got: {out_path}")
    if path.exists() and path.is_dir():
        raise ValueError(f"Output path is a directory: {out_path}")
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, mode=0o700)
        os.chmod(parent, 0o700)  # mkdir mode is masked by umask — set explicitly
    return path


def _validate_iso(value: str | None, name: str) -> str | None:
    """Return the value unchanged after checking it parses as ISO-8601."""
    if value is None or value == "":
        return None
    try:
        datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp, got {value!r}") from exc
    return str(value)


def _collect_rows(engine: Any, since: str | None, until: str | None) -> list[dict]:
    """Page all audit rows (ascending id), applying the since/until ts window."""
    rows: list[dict] = []
    cursor = 0
    while len(rows) < _MAX_ROWS:
        page = engine.rows_after(cursor, since=since, limit=_PAGE_SIZE)
        if not page:
            break
        cursor = int(page[-1]["id"])
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
    if until:
        rows = [r for r in rows if str(r.get("ts", "")) <= until]
    return rows


def _doctor_summary() -> dict:
    """Non-probing environment summary (config / secret-store facts only)."""
    summary: dict[str, Any] = {
        "iaiops_version": _iaiops_version,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    try:
        from iaiops.core.runtime.config import CONFIG_FILE, ENV_FILE, load_config
        from iaiops.core.runtime.secretstore import has_store

        summary["config_file"] = str(CONFIG_FILE)
        summary["config_present"] = CONFIG_FILE.exists()
        summary["secret_store_present"] = bool(has_store())
        summary["plaintext_env_present"] = ENV_FILE.exists()
        config = load_config()
        summary["targets"] = [{"name": t.name, "protocol": t.protocol} for t in config.targets]
    except Exception as exc:  # noqa: BLE001 — evidence export must not crash on config
        summary["config_error"] = str(exc)[:200]
    return summary


def export_evidence_bundle(
    out_path: str | Path,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Export the audit-evidence bundle to ``out_path`` (a ``.zip``).

    Args:
        out_path: Destination zip path; parent created ``0700`` if missing.
        since: Optional ISO-8601 floor on the audit row timestamp (inclusive).
        until: Optional ISO-8601 ceiling on the audit row timestamp (inclusive).

    Returns an immutable-style summary dict:
    ``{path, row_count, chain, files, since, until}``.

    Raises:
        ValueError: on path traversal, wrong extension, or invalid ISO bounds.
    """
    path = validate_output_path(out_path, suffixes=(".zip",))
    since = _validate_iso(since, "since")
    until = _validate_iso(until, "until")
    if since and until and since > until:
        raise ValueError(f"since ({since}) is after until ({until})")

    engine = get_engine()
    rows = _collect_rows(engine, since, until)
    chain = engine.verify_chain()
    doctor = _doctor_summary()

    def _dump(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n"

    jsonl = "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows)
    files = [AUDIT_ROWS_NAME, CHAIN_VERIFICATION_NAME, DOCTOR_SUMMARY_NAME, MANIFEST_NAME]
    rules_path = ops_path("rules.yaml")
    manifest = {
        "bundle": "iaiops audit-evidence bundle",
        "iaiops_version": _iaiops_version,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "since": since,
        "until": until,
        "row_count": len(rows),
        "chain_ok": chain.get("ok", False),
        "rules_yaml_included": rules_path.exists(),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(AUDIT_ROWS_NAME, jsonl)
        bundle.writestr(CHAIN_VERIFICATION_NAME, _dump(chain))
        if rules_path.exists():
            bundle.writestr(RULES_NAME, rules_path.read_text("utf-8"))
            files.insert(2, RULES_NAME)
        bundle.writestr(DOCTOR_SUMMARY_NAME, _dump(doctor))
        bundle.writestr(MANIFEST_NAME, _dump(manifest))
    os.chmod(path, 0o600)
    return {
        "path": str(path),
        "row_count": len(rows),
        "chain": chain,
        "files": files,
        "since": since,
        "until": until,
    }


__all__ = [
    "export_evidence_bundle",
    "validate_output_path",
    "AUDIT_ROWS_NAME",
    "CHAIN_VERIFICATION_NAME",
    "RULES_NAME",
    "DOCTOR_SUMMARY_NAME",
    "MANIFEST_NAME",
]
