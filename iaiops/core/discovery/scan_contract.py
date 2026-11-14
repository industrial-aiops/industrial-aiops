"""Independent, stdlib-only validator for the public scan-evidence v1 format.

This module deliberately imports neither the scanner nor its SQLite store. A
platform can vendor it, or implement the same documented contract independently.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

FORMAT = "iaiops.scan-evidence"
VERSION = "1.0"
MAX_BYTES = 64 * 1024 * 1024
MAX_HOSTS = 100_000
MAX_TEXT = 4096
STATUSES = frozenset(
    {
        "not_requested",
        "not_run",
        "success",
        "refused",
        "unsupported",
        "timeout",
        "missing_dependency",
        "partial",
        "aborted",
        "unknown",
    }
)
FIELD_NAMES = frozenset(
    {
        "vendor",
        "model",
        "name",
        "firmware_version",
        "software_version",
        "hardware_version",
        "reported_revision",
        "physical_serial",
        "source_device_id",
    }
)
VERDICTS = frozenset({"ok", "partial", "no_devices_found", "aborted_unhealthy_segment"})
STAGES = frozenset(
    {"L0_passive", "L0_broadcast", "L1_sweep", "L2_identify", "L3_fingerprint", "L4_browse"}
)
ERROR_CODES = STATUSES - {"success", "not_requested"}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ScanContractError(ValueError):
    """A file cannot be accepted as scan evidence under this contract."""


def _fail(where: str, message: str) -> None:
    raise ScanContractError(f"{where}: {message}")


def _object(value: Any, where: str) -> dict:
    if type(value) is not dict:
        _fail(where, "expected object")
    return value


def _required(value: dict, names: tuple[str, ...], where: str) -> None:
    missing = [name for name in names if name not in value]
    if missing:
        _fail(where, f"missing required keys: {', '.join(missing)}")


def _list(value: Any, where: str, *, cap: int = MAX_HOSTS) -> list:
    if type(value) is not list or len(value) > cap:
        _fail(where, f"expected array of at most {cap} items")
    return value


def _text(value: Any, where: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or len(value) > MAX_TEXT or "\x00" in value:
        _fail(where, "expected bounded text")
    return value


def _time(value: Any, where: str, *, utc: bool = False) -> datetime | None:
    text = _text(value, where, nullable=True)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail(where, "expected ISO 8601 timestamp")
    if parsed.tzinfo is None:
        _fail(where, "timestamp needs timezone")
    if utc and parsed.utcoffset() != timedelta(0):
        _fail(where, "timestamp must be UTC")
    return parsed


def subject_sha256(document: dict) -> str:
    """Stable integrity digest; export time and digest itself are not the subject."""
    subject = {k: document[k] for k in ("source", "observation", "hosts")}
    encoded = json.dumps(
        subject, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_scan_evidence(document: Any) -> dict:
    doc = _object(document, "root")
    _required(
        doc,
        (
            "format",
            "format_version",
            "generator",
            "exported_at",
            "source",
            "observation",
            "hosts",
            "subject_sha256",
        ),
        "root",
    )
    if doc.get("format") != FORMAT:
        _fail("format", f"expected {FORMAT}")
    version = _text(doc.get("format_version"), "format_version")
    if not re.fullmatch(r"[0-9]+\.[0-9]+", version):
        _fail("format_version", "expected major.minor")
    if version.split(".", 1)[0] != "1":
        _fail("format_version", "unsupported major version")
    generator = _object(doc.get("generator"), "generator")
    _required(generator, ("name", "version"), "generator")
    if generator.get("name") != "iaiops":
        _fail("generator.name", "expected iaiops")
    _text(generator.get("version"), "generator.version")
    _time(doc.get("exported_at"), "exported_at", utc=True)
    if doc.get("exported_at") is None:
        _fail("exported_at", "required")
    source = _object(doc.get("source"), "source")
    _required(source, ("id", "assertion"), "source")
    source_id = _text(source.get("id"), "source.id", nullable=True)
    if source_id is not None:
        try:
            uuid.UUID(source_id)
        except ValueError:
            _fail("source.id", "expected UUID")
    if source.get("assertion") != "unverified":
        _fail("source.assertion", "expected unverified")
    obs = _object(doc.get("observation"), "observation")
    _required(
        obs,
        (
            "scan_id",
            "site",
            "collection_domain",
            "started_at",
            "finished_at",
            "profile",
            "verdict",
            "scope",
            "stages",
            "attempted_hosts",
            "wire_summary",
            "errors",
            "truncated",
        ),
        "observation",
    )
    _text(obs.get("scan_id"), "observation.scan_id")
    _text(obs.get("site"), "observation.site", nullable=True)
    _text(obs.get("collection_domain"), "observation.collection_domain", nullable=True)
    started = _time(obs.get("started_at"), "observation.started_at")
    finished = _time(obs.get("finished_at"), "observation.finished_at")
    if started and finished and finished < started:
        _fail("observation", "finished_at precedes started_at")
    _text(obs.get("profile"), "observation.profile")
    if obs.get("verdict") not in VERDICTS:
        _fail("observation.verdict", "unknown verdict")
    scope = _object(obs.get("scope"), "observation.scope")
    _required(
        scope,
        ("cidrs", "hosts", "excluded", "ports", "protocols", "allow_browse"),
        "observation.scope",
    )
    for name in ("cidrs", "hosts", "excluded", "protocols", "allow_browse"):
        value = scope.get(name)
        if value is not None:
            for item in _list(value, f"scope.{name}"):
                _text(item, f"scope.{name}[]")
    ports = scope.get("ports")
    if ports is not None:
        for item in _list(ports, "scope.ports"):
            if type(item) is not int or not 0 < item < 65536:
                _fail("scope.ports", "expected TCP port numbers")
    stages = _list(obs.get("stages"), "observation.stages", cap=20)
    attempted = obs.get("attempted_hosts")
    if attempted is not None:
        for address in _list(attempted, "observation.attempted_hosts"):
            _text(address, "observation.attempted_hosts[]")
    names = set()
    for item in stages:
        stage = _object(item, "stage")
        _required(stage, ("name", "status"), "stage")
        name = _text(stage.get("name"), "stage.name")
        if name in names:
            _fail("stages", "duplicate stage")
        names.add(name)
        if stage.get("status") not in STATUSES:
            _fail("stage.status", "unknown status")
    if names != STAGES:
        _fail("observation.stages", "expected one entry for every scan stage")
    wires = _object(obs.get("wire_summary"), "observation.wire_summary")
    for key, value in wires.items():
        _text(key, "wire_summary key")
        if type(value) is not int or value < 0:
            _fail("wire_summary", "expected nonnegative integer counts")
    if obs.get("truncated") is not None and type(obs["truncated"]) is not bool:
        _fail("observation.truncated", "expected boolean or null")
    for code in _list(obs.get("errors"), "observation.errors", cap=100):
        if code not in ERROR_CODES:
            _fail("observation.errors", "unknown error code")
    hosts = _list(doc.get("hosts"), "hosts")
    addresses = set()
    for host in hosts:
        row = _object(host, "host")
        _required(
            row, ("ip", "mac", "sources", "alive", "ports", "protocols", "identities"), "host"
        )
        address = _text(row.get("ip"), "host.ip")
        if address in addresses:
            _fail("hosts", "duplicate host address")
        addresses.add(address)
        _text(row.get("mac"), "host.mac", nullable=True)
        if type(row.get("alive")) is not bool:
            _fail("host.alive", "expected boolean")
        for item in _list(row.get("sources"), "host.sources", cap=100):
            _text(item, "host.sources[]")
        for item in _list(row.get("ports"), "host.ports", cap=65536):
            port = _object(item, "port")
            _required(port, ("port", "state", "rtt_ms"), "port")
            if type(port.get("port")) is not int or not 0 < port["port"] < 65536:
                _fail("port.port", "expected TCP port number")
            if port.get("state") not in {"open", "refused", "filtered"}:
                _fail("port.state", "unknown state")
            rtt = port.get("rtt_ms")
            if rtt is not None and (type(rtt) not in {int, float} or not 0 <= rtt < 1_000_000):
                _fail("port.rtt_ms", "expected nonnegative number or null")
        protocols = _list(row.get("protocols"), "host.protocols", cap=100)
        for item in protocols:
            proto = _object(item, "protocol")
            _required(proto, ("protocol", "port", "confidence", "evidence", "status"), "protocol")
            _text(proto.get("protocol"), "protocol.protocol")
            port = proto.get("port")
            if port is not None and (type(port) is not int or not 0 < port < 65536):
                _fail("protocol.port", "expected port or null")
            if proto.get("confidence") not in {"confirmed", "port_only"}:
                _fail("protocol.confidence", "unknown confidence")
            _text(proto.get("evidence"), "protocol.evidence")
            if proto.get("status") not in STATUSES:
                _fail("protocol.status", "unknown status")
        identities = _list(row.get("identities"), "host.identities", cap=100)
        identity_protocols = set()
        candidate_protocols = {p["protocol"] for p in protocols}
        for item in identities:
            identity = _object(item, "identity")
            _required(identity, ("protocol", "entity_type", "fields"), "identity")
            protocol = _text(identity.get("protocol"), "identity.protocol")
            if protocol not in candidate_protocols:
                _fail("identity.protocol", "no matching protocol evidence")
            if protocol in identity_protocols:
                _fail("host.identities", "duplicate protocol identity")
            identity_protocols.add(protocol)
            if identity.get("entity_type") not in {None, "device", "server_application", "agent"}:
                _fail("identity.entity_type", "unknown entity type")
            fields = _object(identity.get("fields"), "identity.fields")
            for name, field in fields.items():
                if name not in FIELD_NAMES:
                    _fail("identity.fields", "unsupported field")
                f = _object(field, f"identity.fields.{name}")
                _required(f, ("value", "source_field", "raw_value"), f"identity.fields.{name}")
                _text(f.get("value"), f"identity.fields.{name}.value")
                _text(f.get("source_field"), f"identity.fields.{name}.source_field", nullable=True)
                _text(f.get("raw_value"), f"identity.fields.{name}.raw_value", nullable=True)
    digest = doc.get("subject_sha256")
    if type(digest) is not str or not HEX64.fullmatch(digest):
        _fail("subject_sha256", "expected lowercase SHA-256")
    if subject_sha256(doc) != digest:
        _fail("subject_sha256", "digest mismatch")
    return doc


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            _fail("JSON", f"duplicate key {key!r}")
        out[key] = value
    return out


def load_and_validate(path: str | Path) -> dict:
    source = Path(path)
    if source.stat().st_size > MAX_BYTES:
        _fail("file", "exceeds 64 MiB")
    try:
        doc = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda value: _fail("JSON", f"invalid {value}"),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScanContractError("file: invalid UTF-8 JSON") from exc
    return validate_scan_evidence(doc)
