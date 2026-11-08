"""Project a stored scan onto the bounded, public offline exchange contract."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops import __version__
from iaiops.core.discovery.scan_contract import (
    FORMAT,
    MAX_BYTES,
    MAX_TEXT,
    VERSION,
    ScanContractError,
    load_and_validate,
    subject_sha256,
    validate_scan_evidence,
)
from iaiops.core.governance.decorators import _redact_secrets_text  # noqa: PLC2701
from iaiops.core.governance.evidence import validate_output_path
from iaiops.core.governance.sanitize import sanitize
from iaiops.core.sink.scan_store import load_scan

_CODE = re.compile(r"[a-z0-9_.:-]{1,100}\Z")
_STAGES = (
    "L0_passive",
    "L0_broadcast",
    "L1_sweep",
    "L2_identify",
    "L3_fingerprint",
    "L4_browse",
)
_RAW = {
    "modbus": {"vendor": "vendor", "model": "product_code", "reported_revision": "revision"},
    "opcua": {"name": "application_name", "source_device_id": "application_uri"},
    "s7": {
        "model": "ModuleTypeName/ModuleName",
        "physical_serial": "SerialNumber",
        "firmware_version": "ModuleVersion",
        "hardware_version": "HardwareVersion",
        "name": "ASName",
    },
    "ethernetip": {
        "vendor": "vendor",
        "model": "product_name",
        "physical_serial": "serial",
        "reported_revision": "revision",
    },
    "iolink": {
        "vendor": "vendor",
        "model": "productcode/devicefamily",
        "physical_serial": "serialnumber",
        "software_version": "swrevision",
        "hardware_version": "hwrevision",
        "name": "devicename",
    },
    "mtconnect": {"name": "name", "source_device_id": "uuid"},
}


def _safe(value: Any, *, optional: bool = False) -> str | None:
    if value is None or value == "":
        return None if optional else ""
    if type(value) is not str:
        raise ScanContractError("stored scan contains a non-text public value")
    if len(value) > MAX_TEXT:
        raise ScanContractError("stored scan contains oversized public text")
    return sanitize(_redact_secrets_text(value), MAX_TEXT)


def _field(value: Any, *, source: str | None = None, raw: Any = None) -> dict | None:
    value = _safe(value, optional=True)
    if value is None:
        return None
    raw_text = _safe(raw, optional=True)
    return {"value": value, "source_field": _safe(source, optional=True), "raw_value": raw_text}


def _identity(protocol: str, data: dict) -> dict | None:
    if type(data) is not dict:
        raise ScanContractError("stored protocol identity is not an object")
    extra = data.get("extra") if type(data.get("extra")) is dict else {}
    raw = extra.get("raw_fields") if type(extra.get("raw_fields")) is dict else {}
    sources = extra.get("source_fields") if type(extra.get("source_fields")) is dict else {}
    mapping = _RAW.get(protocol, {})
    fields: dict[str, dict] = {}

    def add(name: str, value: Any, raw_name: str | None = None) -> None:
        # A raw field is evidence that this row came from the new probe. Old
        # records have no provenance and must not get a guessed source label.
        has_raw = name in raw
        item = _field(
            value,
            source=sources.get(name, mapping.get(name)) if has_raw else None,
            raw=raw.get(raw_name or name) if has_raw else None,
        )
        if item is not None:
            fields[name] = item

    for name in ("vendor", "model", "name"):
        if not (protocol == "opcua" and name == "model"):
            if protocol == "s7" and name == "vendor" and name not in raw:
                continue  # Siemens is a probe-side label, not a CPU-reported field.
            add(name, data.get(name))
    if protocol == "mtconnect":
        add("source_device_id", extra.get("source_device_id") or data.get("serial"))
    elif protocol == "opcua":
        add("source_device_id", extra.get("application_uri"))
    else:
        add("physical_serial", data.get("serial"))
    if protocol in {"modbus", "ethernetip"}:
        add("reported_revision", extra.get("reported_revision") or data.get("firmware"))
    elif protocol == "iolink":
        if "software_version" in raw:
            add("software_version", data.get("firmware"))
        else:
            add("reported_revision", data.get("firmware"))
        if "hardware_version" in raw:
            add("hardware_version", extra.get("hardware_version"))
    elif protocol == "s7":
        if "firmware_version" in raw:
            add("firmware_version", data.get("firmware"))
        else:
            add("reported_revision", data.get("firmware"))
        if "hardware_version" in raw:
            add("hardware_version", extra.get("hardware_version"))
    else:
        add("reported_revision", data.get("firmware"))
    if not fields:
        return None
    entity_type = extra.get("entity_type")
    return {"protocol": protocol, "entity_type": entity_type, "fields": fields}


def _protocol_status(candidate: dict) -> str:
    if candidate.get("status") in {
        "success",
        "refused",
        "timeout",
        "missing_dependency",
        "unsupported",
        "unknown",
    }:
        return candidate["status"]
    evidence = candidate.get("evidence", "")
    if evidence == "probe_unavailable":
        return "missing_dependency"
    if type(evidence) is str and evidence.endswith(":rejected"):
        return "refused"
    if candidate.get("confidence") == "confirmed":
        return "success"
    return "unknown"


def _scope_texts(scope: dict, name: str) -> list[str] | None:
    value = scope.get(name)
    if value is None:
        return None
    if type(value) is not list:
        raise ScanContractError(f"stored scope.{name} is not an array")
    return [_safe(item) for item in value]


def build_scan_evidence(record: dict, *, exported_at: str | None = None) -> dict:
    """Build and self-validate a public document from one ``load_scan`` record."""
    if type(record) is not dict or type(record.get("hosts")) is not list:
        raise ScanContractError("stored scan has no host array")
    scope = record.get("scope") or {}
    if type(scope) is not dict:
        raise ScanContractError("stored scan scope is not an object")
    requested = record.get("stages") or []
    statuses = record.get("stage_status") if type(record.get("stage_status")) is dict else {}
    hosts = []
    for host in record.get("hosts", []):
        if type(host) is not dict or type(host.get("identity")) is not dict:
            raise ScanContractError("stored host has no identity object")
        if type(host.get("protocols")) is not list or type(host.get("ports")) is not list:
            raise ScanContractError("stored host has no protocol or port array")
        identities = []
        for protocol, data in sorted((host.get("identity") or {}).items()):
            if type(protocol) is not str or not _CODE.fullmatch(protocol):
                raise ScanContractError("stored identity has an invalid protocol code")
            identity = _identity(protocol, data)
            if identity:
                identities.append(identity)
        candidates = []
        for candidate in host.get("protocols", []):
            if type(candidate) is not dict:
                raise ScanContractError("stored protocol candidate is not an object")
            evidence = candidate.get("evidence")
            candidates.append(
                {
                    "protocol": _safe(candidate.get("protocol")),
                    "port": candidate.get("port") or None,
                    "confidence": candidate.get("confidence"),
                    "evidence": evidence
                    if type(evidence) is str and _CODE.fullmatch(evidence)
                    else "unknown",
                    "status": _protocol_status(candidate),
                }
            )
        hosts.append(
            {
                "ip": _safe(host.get("ip")),
                "mac": _safe(host.get("mac"), optional=True),
                "sources": [_safe(item) for item in host.get("sources", [])],
                "alive": host.get("alive"),
                "ports": [_stored_port(p) for p in host.get("ports", [])],
                "protocols": candidates,
                "identities": identities,
            }
        )
    wires = record.get("wire_summary") or {}
    if type(wires) is not dict or any(
        type(key) is not str or not _CODE.fullmatch(key) for key in wires
    ):
        raise ScanContractError("stored wire summary has invalid keys")
    attempted = record.get("attempted_hosts")
    if attempted is not None:
        if type(attempted) is not list:
            raise ScanContractError("stored attempted_hosts is not an array")
        attempted = [_safe(address) for address in attempted]
    observation = {
        "scan_id": _safe(record.get("scan_id")),
        "site": _safe(record.get("site"), optional=True),
        "collection_domain": None,
        "started_at": record.get("started_at") or None,
        "finished_at": record.get("finished_at") or None,
        "profile": _safe(record.get("profile")),
        "verdict": record.get("verdict"),
        "scope": {
            name: scope.get(name) if name == "ports" else _scope_texts(scope, name)
            for name in ("cidrs", "hosts", "excluded", "ports", "protocols", "allow_browse")
        },
        "stages": [
            {
                "name": name,
                "status": statuses.get(name, "unknown") if name in requested else "not_requested",
            }
            for name in _STAGES
        ],
        "attempted_hosts": attempted,
        "wire_summary": wires,
        "errors": ["unknown"]
        if record.get("notes") or any(h.get("errors") for h in record.get("hosts", []))
        else [],
        # New exports never cut host/evidence rows to fit: the plan refuses
        # excessive scope and export refuses an oversized document. Legacy
        # rows have no body fingerprint, so their completeness is unknown.
        "truncated": False if record.get("body_sha256") else None,
    }
    doc = {
        "format": FORMAT,
        "format_version": VERSION,
        "generator": {"name": "iaiops", "version": __version__},
        "exported_at": exported_at or datetime.now(UTC).isoformat(),
        "source": {"id": record.get("source_id"), "assertion": "unverified"},
        "observation": observation,
        "hosts": sorted(hosts, key=lambda row: row["ip"]),
    }
    doc["subject_sha256"] = subject_sha256(doc)
    return validate_scan_evidence(doc)


def _stored_port(port: Any) -> dict:
    if type(port) is not dict:
        raise ScanContractError("stored port is not an object")
    return {"port": port.get("port"), "state": port.get("state"), "rtt_ms": port.get("rtt_ms")}


def export_scan(
    scan_id: str, out: str | Path, *, db: str | Path | None = None, overwrite: bool = False
) -> dict:
    """Export a named stored scan, validate, then publish atomically on this box."""
    if not scan_id or not re.fullmatch(r"[0-9a-f]{16}", scan_id):
        raise ValueError("scan ID must be the 16-character ID from `iaiops scan list`")
    record = load_scan(scan_id, db)
    document = build_scan_evidence(record)
    path = validate_output_path(out, suffixes=(".json",))
    if path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {path}; pass --overwrite to replace it")
    payload = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ScanContractError("export exceeds 64 MiB")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".scan-evidence-", suffix=".json", delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        load_and_validate(temporary)
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # atomic create; existing destination fails
            temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "path": str(path),
        "scan_id": scan_id,
        "hosts": len(document["hosts"]),
        "subject_sha256": document["subject_sha256"],
        "bytes": len(payload),
    }
