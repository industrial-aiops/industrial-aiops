"""Offline exchange contract, conflict handling and the CLI's output boundary."""

from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from iaiops.cli.scan import scan_app
from iaiops.core.discovery.scan_contract import (
    ScanContractError,
    load_and_validate,
    subject_sha256,
    validate_scan_evidence,
)
from iaiops.core.discovery.scan_export import build_scan_evidence, export_scan
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    HostResult,
    ProtocolCandidate,
    ScanPlan,
    ScanResult,
)
from iaiops.core.sink.scan_store import (
    CREATE_SCAN_HOSTS_TABLE,
    CREATE_SCANS_TABLE,
    ScanConflict,
    load_scan,
    save_scan,
)

pytestmark = pytest.mark.unit


def _result(*, serial: str = "00042", started: str = "2026-10-30T08:00:00+00:00") -> ScanResult:
    host = HostResult(
        ip="10.2.0.4",
        protocols=(ProtocolCandidate("s7", CONF_CONFIRMED, "s7_cpu_info", port=102),),
        identity={
            "s7": {
                "vendor": "Siemens",
                "serial": serial,
                "extra": {
                    "hardware_version": "3.1",
                    "raw_fields": {
                        "physical_serial": serial,
                        "hardware_version": "3.1",
                    },
                },
            }
        },
    )
    return ScanResult(
        plan=ScanPlan(site="Plant A", hosts=("10.2.0.4",)),
        hosts=(host,),
        started_at=started,
        finished_at="2026-10-30T08:01:00+00:00",
        stage_status={"L0_passive": "success", "L1_sweep": "success"},
        attempted_hosts=("10.2.0.4",),
    )


def test_export_round_trip_and_repeat_subject(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    export_scan(scan_id, first, db=db)
    export_scan(scan_id, second, db=db)
    a = load_and_validate(first)
    b = load_and_validate(second)
    assert a["source"]["id"] == load_scan(scan_id, db)["source_id"]
    assert a["subject_sha256"] == b["subject_sha256"]
    assert a["observation"]["attempted_hosts"] == ["10.2.0.4"]
    assert a["observation"]["truncated"] is False
    fields = a["hosts"][0]["identities"][0]["fields"]
    assert fields["physical_serial"] == {
        "value": "00042",
        "source_field": "SerialNumber",
        "raw_value": "00042",
    }
    assert fields["hardware_version"]["value"] == "3.1"


def test_conflict_preserves_original_and_source_id(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    original = load_scan(scan_id, db)
    with pytest.raises(ScanConflict):
        save_scan(_result(serial="00999"), db)
    assert load_scan(scan_id, db) == original
    assert save_scan(_result(), db) == scan_id


def test_old_row_exports_unknown_without_backfill(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE scans SET source_id=NULL, stage_status=NULL, attempted_hosts=NULL "
            "WHERE scan_id=?",
            (scan_id,),
        )
    out = tmp_path / "legacy.json"
    export_scan(scan_id, out, db=db)
    doc = load_and_validate(out)
    assert doc["source"]["id"] is None
    assert doc["observation"]["stages"][0]["status"] == "unknown"
    assert doc["observation"]["attempted_hosts"] is None


def test_actual_legacy_schema_exports_without_migrating_database(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(CREATE_SCANS_TABLE)
        conn.execute(CREATE_SCAN_HOSTS_TABLE)
        conn.execute(
            "INSERT INTO scans (scan_id, site, started_at, finished_at, profile, verdict, "
            "stages, scope, wire_summary, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "0123456789abcdef",
                "old site",
                "2026-10-30T08:00:00+00:00",
                "2026-10-30T08:01:00+00:00",
                "inventory",
                "no_devices_found",
                '["L0_passive"]',
                '{"cidrs":[],"hosts":[],"excluded":[],"ports":[],"protocols":[]}',
                "{}",
                "[]",
            ),
        )
        before = [row[1] for row in conn.execute("PRAGMA table_info(scans)")]
    out = tmp_path / "legacy.json"
    export_scan("0123456789abcdef", out, db=db)
    doc = load_and_validate(out)
    assert doc["source"]["id"] is None
    assert doc["observation"]["scope"]["allow_browse"] is None
    assert doc["observation"]["truncated"] is None
    with sqlite3.connect(db) as conn:
        after = [row[1] for row in conn.execute("PRAGMA table_info(scans)")]
    assert after == before


def test_no_overwrite_and_no_partial_file(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    out = tmp_path / "evidence.json"
    out.write_text("keep")
    with pytest.raises(FileExistsError):
        export_scan(scan_id, out, db=db)
    assert out.read_text() == "keep"
    assert list(tmp_path.glob(".scan-evidence-*")) == []
    export_scan(scan_id, out, db=db, overwrite=True)
    load_and_validate(out)


def test_validator_rejects_tamper_version_duplicates_and_nan(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    out = tmp_path / "evidence.json"
    export_scan(scan_id, out, db=db)
    doc = load_and_validate(out)
    original_digest = doc["subject_sha256"]
    doc["generator"]["version"] = "future-version"
    doc["exported_at"] = "2026-10-31T00:00:00+00:00"
    assert subject_sha256(doc) == original_digest
    doc["hosts"][0]["ip"] = "10.2.0.5"
    with pytest.raises(ScanContractError, match="digest mismatch"):
        validate_scan_evidence(doc)
    doc["subject_sha256"] = subject_sha256(doc)
    validate_scan_evidence(doc)
    doc["format_version"] = "2.0"
    with pytest.raises(ScanContractError, match="unsupported major"):
        validate_scan_evidence(doc)
    out.write_text('{"format":"x","format":"y"}')
    with pytest.raises(ScanContractError, match="duplicate key"):
        load_and_validate(out)
    out.write_text('{"x":NaN}')
    with pytest.raises(ScanContractError):
        load_and_validate(out)


def test_identity_does_not_publish_raw_errors_or_authorization(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE scans SET notes=? WHERE scan_id=?",
            (json.dumps(["token=do-not-export"]), scan_id),
        )
        conn.execute(
            "UPDATE scan_hosts SET identity_json=? WHERE scan_id=?",
            (json.dumps({"s7": {"name": "password=do-not-export", "serial": "00042"}}), scan_id),
        )
    out = tmp_path / "evidence.json"
    export_scan(scan_id, out, db=db)
    text = out.read_text()
    assert "do-not-export" not in text
    assert '"errors": [\n      "unknown"' in text


def test_shared_fixture_contract():
    root = Path(__file__).parent / "data" / "scan_evidence_v1"
    for name in ("valid", "partial", "aborted", "empty"):
        sample = load_and_validate(root / f"{name}.json")
        assert sample["format_version"] == "1.0"
        assert sample["observation"]["truncated"] is False
    with pytest.raises(ScanContractError, match="duplicate protocol identity"):
        load_and_validate(root / "duplicate_identity.invalid.json")


def test_cli_export_is_offline_and_requires_exact_id(tmp_path, monkeypatch):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)

    def no_packets(*args, **kwargs):
        raise AssertionError("scan export opened a network connection")

    monkeypatch.setattr(socket, "create_connection", no_packets)
    runner = CliRunner()
    out = tmp_path / "evidence.json"
    result = runner.invoke(scan_app, ["export", scan_id, "--db", str(db), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert load_and_validate(out)["observation"]["scan_id"] == scan_id
    missing = runner.invoke(scan_app, ["export", "bad", "--db", str(db), "--out", str(out)])
    assert missing.exit_code == 1
    assert "scan ID must be" in missing.output


def test_legacy_version_and_uuid_kinds_are_not_guessed(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    record = load_scan(scan_id, db)
    record["hosts"][0]["identity"] = {
        "s7": {"firmware": "3.1", "serial": "00042"},
        "mtconnect": {"serial": "machine-uuid"},
    }
    record["hosts"][0]["protocols"].append(
        {
            "protocol": "mtconnect",
            "confidence": "confirmed",
            "port": 5000,
            "evidence": "mtconnect_probe",
            "status": "unknown",
        }
    )
    doc = build_scan_evidence(record)
    by_protocol = {item["protocol"]: item for item in doc["hosts"][0]["identities"]}
    s7 = by_protocol["s7"]
    assert "firmware_version" not in s7["fields"]
    assert s7["fields"]["reported_revision"]["source_field"] is None
    assert s7["entity_type"] is None
    assert by_protocol["mtconnect"]["fields"]["source_device_id"]["value"] == "machine-uuid"
    assert "physical_serial" not in by_protocol["mtconnect"]["fields"]


def test_export_rejects_malformed_and_oversized_stored_values(tmp_path):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    base = load_scan(scan_id, db)
    bad_candidate = json.loads(json.dumps(base))
    bad_candidate["hosts"][0]["protocols"].append(42)
    with pytest.raises(ScanContractError, match="candidate is not an object"):
        build_scan_evidence(bad_candidate)

    bad_raw = json.loads(json.dumps(base))
    bad_raw["hosts"][0]["identity"]["s7"]["extra"]["raw_fields"]["physical_serial"] = ["00042"]
    with pytest.raises(ScanContractError, match="non-text public value"):
        build_scan_evidence(bad_raw)

    oversized = json.loads(json.dumps(base))
    oversized["hosts"][0]["identity"]["s7"]["serial"] = "0" * 4097
    with pytest.raises(ScanContractError, match="oversized public text"):
        build_scan_evidence(oversized)


def test_export_rejects_bad_path_and_cleans_failed_temp(tmp_path, monkeypatch):
    db = tmp_path / "scan.db"
    scan_id = save_scan(_result(), db)
    with pytest.raises(ValueError, match="traversal"):
        export_scan(scan_id, tmp_path / ".." / "escape.json", db=db)
    with pytest.raises(ValueError, match="must end"):
        export_scan(scan_id, tmp_path / "evidence.txt", db=db)

    from iaiops.core.discovery import scan_export

    out = tmp_path / "evidence.json"
    out.write_text("original")

    def broken_validator(path):
        raise ScanContractError("injected validation failure")

    monkeypatch.setattr(scan_export, "load_and_validate", broken_validator)
    with pytest.raises(ScanContractError, match="injected"):
        export_scan(scan_id, out, db=db, overwrite=True)
    assert out.read_text() == "original"
    assert list(tmp_path.glob(".scan-evidence-*")) == []
