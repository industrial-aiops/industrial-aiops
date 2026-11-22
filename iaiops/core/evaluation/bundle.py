"""Bounded local evaluation/feedback reproduction archives, unsigned inventories."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

from iaiops import __version__
from iaiops.core.evaluation.pdm import evaluate
from iaiops.core.governance.evidence import validate_output_path
from iaiops.core.readiness.diagnostic_export import json_bytes


def engine_hashes() -> dict:
    from iaiops.core.brain import _shared, maintenance_log, pdm, pdm_math, pdm_patterns, pdm_rul
    from iaiops.core.evaluation import feedback
    from iaiops.core.evaluation import pdm as evaluation
    from iaiops.core.knowledge import case_store, cases
    from iaiops.core.readiness import diagnostic

    return {
        m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
        for m in (
            pdm,
            pdm_math,
            pdm_patterns,
            pdm_rul,
            evaluation,
            feedback,
            maintenance_log,
            _shared,
            cases,
            case_store,
            diagnostic,
        )
    }


def export_bundle(out: Path, entries: dict[str, bytes]) -> None:
    manifest = {
        "schema": "iaiops.pdm-bundle/v1",
        "package_version": __version__,
        "source_state": "local invocation; package metadata alone is not a source revision",
        "engine_sha256": engine_hashes(),
        "unsigned_inventory": True,
        "files": {
            n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
            for n, b in entries.items()
        },
    }
    if sum(len(b) for b in entries.values()) + len(json_bytes(manifest)) > 8_000_000:
        raise ValueError("Expanded evidence bundle exceeds 8 MB")
    target = validate_output_path(out, suffixes=(".zip",))
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with (
        os.fdopen(fd, "wb") as stream,
        zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z,
    ):
        for name, body in entries.items():
            z.writestr(name, body)
        z.writestr("manifest.json", json_bytes(manifest))


def read_evaluation(path: Path) -> tuple[dict, bytes, bytes, bytes]:
    path = path.expanduser()
    if path.stat().st_size > 8_000_000:
        raise ValueError("Evaluation archive exceeds 8 MB")
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            expected = {"input.json", "evaluation.json", "audit-reference.json", "manifest.json"}
            if len(names) != len(expected) or set(names) != expected:
                raise ValueError("Unexpected/duplicate archive entries")
            if sum(i.file_size for i in z.infolist()) > 8_000_000:
                raise ValueError("Expanded archive exceeds 8 MB")
            entries = {n: z.read(n) for n in names}
        manifest = json.loads(entries["manifest.json"])
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != "iaiops.pdm-bundle/v1"
            or manifest.get("engine_sha256") != engine_hashes()
        ):
            raise ValueError("Incompatible evaluation engine; rerun with the pinned source")
        if not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != expected - {
            "manifest.json"
        }:
            raise ValueError("Incomplete inventory")
        for name, entry in manifest["files"].items():
            if entry != {
                "sha256": hashlib.sha256(entries[name]).hexdigest(),
                "bytes": len(entries[name]),
            }:
                raise ValueError("Evaluation evidence hash mismatch")
        report = json.loads(entries["evaluation.json"])
        if evaluate(json.loads(entries["input.json"])) != report:
            raise ValueError("Evaluation does not reproduce from input")
        return (
            report,
            entries["input.json"],
            entries["evaluation.json"],
            entries["audit-reference.json"],
        )
    except (zipfile.BadZipFile, KeyError, TypeError) as exc:
        raise ValueError("Invalid evaluation bundle") from exc
