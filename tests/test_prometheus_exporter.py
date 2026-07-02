"""Prometheus exporter (queryability layer) — text-format rendering + HTTP smoke.

Rendering runs against tmp_path stores; the endpoint smoke test binds an
ephemeral loopback port (port=0) and scrapes it with urllib.
"""

from __future__ import annotations

import sqlite3
import urllib.error
import urllib.request

import pytest

from iaiops.core.sink.prometheus import (
    CONTENT_TYPE,
    GAUGE_NAME,
    MetricsServer,
    render_metrics,
)
from iaiops.core.sink.push import historian_push


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "data.db"
    points = [
        {"ref": "line1.temp", "value": 21.5, "timestamp": "2026-07-01T00:00:00Z",
         "quality": "good", "unit": "C"},
        {"ref": "line1.temp", "value": 23.5, "timestamp": "2026-07-01T01:00:00Z",
         "quality": "good", "unit": "C"},
        {"ref": "line1.state", "value": "RUNNING"},  # text → export-only, no gauge
    ]
    assert "error" not in historian_push(points, "sqlite", db_path=path,
                                         endpoint="plc1", protocol="modbus")
    return path


@pytest.fixture()
def audit_db(tmp_path):
    path = tmp_path / "audit.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, status TEXT)")
    conn.executemany("INSERT INTO audit_log (status) VALUES (?)",
                     [("ok",), ("ok",), ("error",)])
    conn.commit()
    conn.close()
    return path


@pytest.mark.unit
def test_render_gauges_latest_numeric_only(store, tmp_path):
    text = render_metrics(store, audit_db_path=tmp_path / "no-audit.db")
    assert f"# HELP {GAUGE_NAME}" in text
    assert f"# TYPE {GAUGE_NAME} gauge" in text
    assert (f'{GAUGE_NAME}{{endpoint="plc1",protocol="modbus",'
            f'tag="line1.temp",unit="C"}} 23.5') in text
    assert "line1.state" not in text  # text values are not gauges
    assert "iaiops_samples_written_total 3" in text
    assert "iaiops_audit_events_total 0" in text  # missing audit db → 0, no crash
    assert text.endswith("\n")


@pytest.mark.unit
def test_render_audit_counters(store, audit_db):
    text = render_metrics(store, audit_db_path=audit_db)
    assert "iaiops_audit_events_total 3" in text
    assert "iaiops_tool_errors_total 1" in text
    assert "# TYPE iaiops_audit_events_total counter" in text


@pytest.mark.unit
def test_render_empty_store_is_valid(tmp_path):
    text = render_metrics(tmp_path / "missing.db", tmp_path / "missing-audit.db")
    assert "iaiops_samples_written_total 0" in text
    assert f"{GAUGE_NAME}{{" not in text  # no series, but HELP/TYPE still present


@pytest.mark.unit
def test_label_escaping(tmp_path):
    path = tmp_path / "data.db"
    historian_push(
        [{"ref": 'we"ird\\tag\nname', "value": 1.0}], "sqlite", db_path=path,
    )
    text = render_metrics(path, audit_db_path=tmp_path / "no-audit.db")
    assert 'tag="we\\"ird\\\\tag\\nname"' in text


@pytest.mark.unit
def test_http_endpoint_smoke(store, tmp_path):
    server = MetricsServer(host="127.0.0.1", port=0, db_path=store,
                           audit_db_path=tmp_path / "no-audit.db")
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/metrics"
        with urllib.request.urlopen(url, timeout=5) as resp:  # nosec B310 — local test
            assert resp.status == 200
            assert resp.headers["Content-Type"] == CONTENT_TYPE
            body = resp.read().decode("utf-8")
        assert GAUGE_NAME in body and "iaiops_samples_written_total 3" in body
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(  # nosec B310 — local test
                f"http://127.0.0.1:{server.port}/secrets", timeout=5
            )
        assert exc_info.value.code == 404
    finally:
        server.stop()


@pytest.mark.unit
def test_server_rejects_bad_port():
    with pytest.raises(ValueError, match="port"):
        MetricsServer(port=99999)
