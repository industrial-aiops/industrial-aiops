"""On-box storage for site scans — the tables the device inventory is read from.

Lives beside the ``samples`` table in the same local database and never touches
it: a survey and a data collection are different products of the same box, and
one filling up must not corrupt the other.

Two shapes are stored rather than one, and the redundancy is deliberate:

* the **full result** as JSON, so nothing observed is lost to a schema that did
  not anticipate it;
* the **flat columns** a person actually queries — ip, mac, vendor, model,
  serial, open ports — so the device table is a ``SELECT`` and not a program.

Where a host speaks two protocols, the flat columns come from ONE of them and
``identity_from`` names which. A row that silently merged a Modbus vendor with
an OPC-UA model would describe a device that does not exist; the JSON keeps both
in full.

There is no retention limit here and nothing is pruned by default. Cleanup is
offered (:func:`prune_scans`) and never imposed — an on-box store that quietly
discards last month's survey is worse than one that grows.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    PORT_OPEN,
    HostResult,
    ScanResult,
)
from iaiops.core.sink.sqlite_local import (
    _connect,  # noqa: PLC2701 — same package; the hardened connect is the point
    _harden_permissions,  # noqa: PLC2701
    local_db_path,
)

#: Flat identity columns, in the order the report renders them.
IDENTITY_COLUMNS = ("vendor", "model", "serial", "firmware", "name")

CREATE_SCANS_TABLE = """\
CREATE TABLE IF NOT EXISTS scans (
    scan_id      TEXT PRIMARY KEY,
    site         TEXT NOT NULL DEFAULT '',
    started_at   TEXT NOT NULL DEFAULT '',
    finished_at  TEXT NOT NULL DEFAULT '',
    profile      TEXT NOT NULL DEFAULT '',
    verdict      TEXT NOT NULL DEFAULT '',
    stages       TEXT NOT NULL DEFAULT '[]',
    scope        TEXT NOT NULL DEFAULT '{}',
    approved_by  TEXT NOT NULL DEFAULT '',
    ticket       TEXT NOT NULL DEFAULT '',
    wire_summary TEXT NOT NULL DEFAULT '{}',
    notes        TEXT NOT NULL DEFAULT '[]',
    host_count   INTEGER NOT NULL DEFAULT 0,
    device_count INTEGER NOT NULL DEFAULT 0
)
"""

CREATE_SCAN_HOSTS_TABLE = """\
CREATE TABLE IF NOT EXISTS scan_hosts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       TEXT NOT NULL,
    ip            TEXT NOT NULL DEFAULT '',
    mac           TEXT NOT NULL DEFAULT '',
    sources       TEXT NOT NULL DEFAULT '',
    alive         INTEGER NOT NULL DEFAULT 0,
    open_ports    TEXT NOT NULL DEFAULT '',
    confirmed     TEXT NOT NULL DEFAULT '',
    identity_from TEXT NOT NULL DEFAULT '',
    vendor        TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    serial        TEXT NOT NULL DEFAULT '',
    firmware      TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL DEFAULT '',
    ports_json    TEXT NOT NULL DEFAULT '[]',
    protocols_json TEXT NOT NULL DEFAULT '[]',
    identity_json TEXT NOT NULL DEFAULT '{}',
    errors_json   TEXT NOT NULL DEFAULT '[]',
    UNIQUE (scan_id, ip)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_scans_started ON scans (started_at)",
    "CREATE INDEX IF NOT EXISTS idx_scan_hosts_scan ON scan_hosts (scan_id)",
    "CREATE INDEX IF NOT EXISTS idx_scan_hosts_mac ON scan_hosts (mac)",
)


class ScanNotFound(LookupError):
    """No scan with that id. Distinct from a scan that found nothing."""


def scan_id_for(result: ScanResult) -> str:
    """A deterministic id: the same result stored twice is the same row.

    Content-addressed rather than random, so re-storing after a crash updates
    one row instead of accumulating near-duplicate surveys that a diff would
    then report as change.
    """
    material = json.dumps(
        {
            "site": result.plan.site,
            "started": result.started_at,
            "profile": result.plan.profile,
            "cidrs": list(result.plan.cidrs),
            "hosts": list(result.plan.hosts),
            "stages": list(result.plan.stages),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _open_ports(host: HostResult) -> str:
    return ",".join(str(p.port) for p in host.ports if p.state == PORT_OPEN)


def _confirmed(host: HostResult) -> tuple[str, ...]:
    return tuple(c.protocol for c in host.protocols if c.confidence == CONF_CONFIRMED)


def _flat_identity(host: HostResult) -> tuple[str, dict[str, str]]:
    """Pick ONE protocol's identity for the flat columns, and say which.

    Merging two protocols' fields would describe a device that does not exist —
    a Modbus vendor next to an OPC-UA model is not a row anyone can act on. The
    first confirmed protocol that actually returned fields wins; the full,
    per-protocol identity stays in JSON either way.
    """
    for protocol in _confirmed(host):
        fields = host.identity.get(protocol) or {}
        flat = {k: str(fields.get(k, "")) for k in IDENTITY_COLUMNS}
        if any(flat.values()):
            return protocol, flat
    return "", dict.fromkeys(IDENTITY_COLUMNS, "")


def _host_row(scan_id: str, host: HostResult) -> tuple:
    source, flat = _flat_identity(host)
    return (
        scan_id,
        s(host.ip, 64),
        s(host.mac, 24),
        ",".join(host.sources),
        int(host.alive),
        _open_ports(host),
        ",".join(_confirmed(host)),
        source,
        *(s(flat[k], 128) for k in IDENTITY_COLUMNS),
        json.dumps([{"port": p.port, "state": p.state, "rtt_ms": p.rtt_ms} for p in host.ports]),
        json.dumps(
            [
                {
                    "protocol": c.protocol,
                    "confidence": c.confidence,
                    "port": c.port,
                    "evidence": c.evidence,
                    "detail": c.detail,
                }
                for c in host.protocols
            ]
        ),
        json.dumps(host.identity, default=str),
        json.dumps(list(host.errors)),
    )


def host_to_dict(host: HostResult) -> dict[str, Any]:
    """A host in the SAME shape :func:`load_scan` returns, without storing it.

    One shape with two producers, so a report renders identically whether the
    scan came off disk or straight out of the runner. Pinned by a test that
    compares the two key-for-key — a renderer that silently worked on only one
    of them would be a bug nobody noticed until an operator asked for a report
    of a scan they had not saved.
    """
    source, flat = _flat_identity(host)
    return {
        "ip": host.ip,
        "mac": host.mac,
        "sources": list(host.sources),
        "alive": host.alive,
        "open_ports": [p.port for p in host.ports if p.state == PORT_OPEN],
        "confirmed": list(_confirmed(host)),
        "identity_from": source,
        **{k: flat[k] for k in IDENTITY_COLUMNS},
        "ports": [{"port": p.port, "state": p.state, "rtt_ms": p.rtt_ms} for p in host.ports],
        "protocols": [
            {
                "protocol": c.protocol,
                "confidence": c.confidence,
                "port": c.port,
                "evidence": c.evidence,
                "detail": c.detail,
            }
            for c in host.protocols
        ],
        "identity": json.loads(json.dumps(host.identity, default=str)),
        "errors": list(host.errors),
    }


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(CREATE_SCANS_TABLE)
    conn.execute(CREATE_SCAN_HOSTS_TABLE)
    for ddl in _INDEXES:
        conn.execute(ddl)
    conn.commit()


def _db(db_path: Path | str | None) -> Path:
    return Path(db_path).expanduser() if db_path else local_db_path()


def save_scan(result: ScanResult, db_path: Path | str | None = None) -> str:
    """Persist a scan and its hosts. Returns the scan id. Idempotent.

    Re-saving the same scan REPLACES its rows rather than appending: a survey
    stored twice is one survey, and a store that duplicated it would make the
    next comparison report change that never happened.
    """
    path = _db(db_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    scan_id = scan_id_for(result)
    plan = result.plan

    conn = _connect(path)
    try:
        _ensure_schema(conn)
        with conn:  # one transaction: a half-written scan is worse than none
            conn.execute("DELETE FROM scan_hosts WHERE scan_id = ?", (scan_id,))
            conn.execute(
                "INSERT OR REPLACE INTO scans (scan_id, site, started_at, finished_at, "
                "profile, verdict, stages, scope, approved_by, ticket, wire_summary, "
                "notes, host_count, device_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    scan_id,
                    s(plan.site, 96),
                    result.started_at,
                    result.finished_at,
                    s(plan.profile, 32),
                    result.verdict,
                    json.dumps(list(plan.stages)),
                    json.dumps(
                        {
                            "cidrs": list(plan.cidrs),
                            "hosts": list(plan.hosts),
                            "excluded": list(plan.excluded),
                            "ports": list(plan.ports),
                            "protocols": list(plan.protocols),
                            "seed": plan.seed,
                        }
                    ),
                    s(plan.authorization.approved_by, 96),
                    s(plan.authorization.ticket, 64),
                    json.dumps(result.wire_summary),
                    json.dumps(list(result.notes)),
                    len(result.hosts),
                    len(result.devices),
                ),
            )
            conn.executemany(
                "INSERT INTO scan_hosts (scan_id, ip, mac, sources, alive, open_ports, "
                "confirmed, identity_from, vendor, model, serial, firmware, name, "
                "ports_json, protocols_json, identity_json, errors_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [_host_row(scan_id, h) for h in result.hosts],
            )
    finally:
        conn.close()
    _harden_permissions(path)
    return scan_id


@dataclass(frozen=True)
class ScanSummary:
    """One stored scan, without its hosts — what a listing shows."""

    scan_id: str
    site: str
    started_at: str
    finished_at: str
    profile: str
    verdict: str
    host_count: int
    device_count: int
    approved_by: str
    ticket: str


def list_scans(db_path: Path | str | None = None, limit: int = 50) -> tuple[ScanSummary, ...]:
    """Stored scans, newest first."""
    path = _db(db_path)
    if not path.exists():
        return ()
    conn = _connect(path)
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT scan_id, site, started_at, finished_at, profile, verdict, "
            "host_count, device_count, approved_by, ticket FROM scans "
            "ORDER BY started_at DESC, scan_id DESC LIMIT ?",
            (max(1, min(int(limit), 10_000)),),
        ).fetchall()
    finally:
        conn.close()
    return tuple(ScanSummary(*row) for row in rows)


def load_scan(scan_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    """One stored scan with its hosts, as plain dicts ready for a renderer.

    Deliberately not rebuilt into :class:`ScanResult`: a report renders what was
    stored, and reconstructing dataclasses would quietly drop any field a later
    schema version added.
    """
    path = _db(db_path)
    if not path.exists():
        raise ScanNotFound(f"no scan store at {path}")
    conn = _connect(path)
    try:
        _ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        scan = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
        if scan is None:
            raise ScanNotFound(f"no scan {scan_id!r} in {path}")
        hosts = conn.execute(
            "SELECT * FROM scan_hosts WHERE scan_id = ? ORDER BY id", (scan_id,)
        ).fetchall()
    finally:
        conn.close()

    record = dict(scan)
    for field in ("stages", "scope", "wire_summary", "notes"):
        record[field] = json.loads(record[field])
    record["hosts"] = [_host_dict(row) for row in hosts]
    return record


def _host_dict(row: sqlite3.Row) -> dict[str, Any]:
    host = dict(row)
    host["alive"] = bool(host["alive"])
    host["sources"] = [x for x in host["sources"].split(",") if x]
    host["open_ports"] = [int(x) for x in host["open_ports"].split(",") if x]
    host["confirmed"] = [x for x in host["confirmed"].split(",") if x]
    for field in ("ports", "protocols", "identity", "errors"):
        host[field] = json.loads(host.pop(f"{field}_json"))
    return host


def prune_scans(keep_last: int, db_path: Path | str | None = None) -> int:
    """Delete all but the ``keep_last`` newest scans. Returns how many went.

    Offered, never applied on its own. An on-box store that silently discarded
    last month's survey would be worse than one that grows — the operator
    decides, and the count is returned so the decision is visible.
    """
    if keep_last < 1:
        raise ValueError("keep_last must be at least 1 — refusing to delete every scan")
    path = _db(db_path)
    if not path.exists():
        return 0
    conn = _connect(path)
    try:
        _ensure_schema(conn)
        with conn:
            doomed = [
                row[0]
                for row in conn.execute(
                    "SELECT scan_id FROM scans ORDER BY started_at DESC, scan_id DESC "
                    "LIMIT -1 OFFSET ?",
                    (keep_last,),
                ).fetchall()
            ]
            for scan_id in doomed:
                conn.execute("DELETE FROM scan_hosts WHERE scan_id = ?", (scan_id,))
                conn.execute("DELETE FROM scans WHERE scan_id = ?", (scan_id,))
    finally:
        conn.close()
    return len(doomed)


__all__ = [
    "IDENTITY_COLUMNS",
    "host_to_dict",
    "ScanNotFound",
    "ScanSummary",
    "scan_id_for",
    "save_scan",
    "list_scans",
    "load_scan",
    "prune_scans",
]
