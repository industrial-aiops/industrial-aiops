"""Integration tests against a REAL in-process asyncua OPC-UA server.

A module-scoped fixture starts an ``asyncua.sync.Server`` exposing a small
address space (a Line1 folder with Temperature / Pressure variables and a
MotorFault boolean), then the ops layer connects to it with a real
``asyncua.sync.Client`` over ``opc.tcp://``. No mocking of the OPC-UA stack —
this exercises browse / read / sample / alarm / health for real.
"""

from __future__ import annotations

import socket

import pytest

from iaiops.connectors.opcua import ops
from iaiops.core.brain import analysis
from iaiops.core.runtime.config import TargetConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def opcua_server():
    """Start a real in-process OPC-UA server; yield its endpoint URL + node ids."""
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/aiops"
    srv = Server()
    srv.set_endpoint(url)
    srv.set_server_name("iaiops-test")
    idx = srv.register_namespace("http://aiops.test")
    objects = srv.nodes.objects
    line = objects.add_folder(idx, "Line1")
    temp = line.add_variable(idx, "Temperature", 85.0)
    press = line.add_variable(idx, "Pressure", 4.2)
    fault = line.add_variable(idx, "MotorFault", True)
    srv.start()
    history_ok = True
    try:
        # Enable Historical Access (HDA) on the temperature node so the
        # read_history path is exercised against a REAL server, not a mock.
        srv.historize_node_data_change(temp, period=None, count=100)
        temp.set_value(85.5)
        temp.set_value(86.0)
        temp.set_value(85.0)  # restore the value other tests assert
    except Exception:  # noqa: BLE001 — some asyncua builds vary; fall back to "unsupported"
        history_ok = False
    try:
        yield {
            "url": url,
            "temp": temp.nodeid.to_string(),
            "press": press.nodeid.to_string(),
            "fault": fault.nodeid.to_string(),
            "history_ok": history_ok,
        }
    finally:
        srv.stop()


def _target(url: str, tags=()) -> TargetConfig:
    return TargetConfig(name="line1", protocol="opcua", endpoint_url=url, tags=tags)


@pytest.mark.integration
def test_server_info_real(opcua_server):
    info = ops.server_info(_target(opcua_server["url"]))
    assert info["state"] == 0
    assert info["namespace_count"] >= 3
    assert any("aiops.test" in n for n in info["namespaces"])


@pytest.mark.integration
def test_browse_real(opcua_server):
    nodes = ops.browse(_target(opcua_server["url"]), node_id="i=85", depth=2)
    names = {n["browse_name"] for n in nodes}
    assert "Line1" in names
    assert "Temperature" in names


@pytest.mark.integration
def test_read_node_real(opcua_server):
    r = ops.read_node(_target(opcua_server["url"]), opcua_server["temp"])
    assert r["value"] == 85.0
    assert r["datatype"] == "Double"
    assert r["good"] is True
    assert "error" not in r


@pytest.mark.integration
def test_read_many_real(opcua_server):
    rows = ops.read_many(
        _target(opcua_server["url"]), [opcua_server["temp"], opcua_server["press"]]
    )
    values = {row["value"] for row in rows}
    assert values == {85.0, 4.2}


@pytest.mark.integration
def test_subscribe_sample_is_bounded_real(opcua_server):
    out = ops.subscribe_sample(
        _target(opcua_server["url"]), opcua_server["temp"],
        samples=3, interval_ms=50, timeout_s=5,
    )
    assert out["requested_samples"] == 3
    assert out["collected"] == 3
    assert all(s["value"] == 85.0 for s in out["samples"])


@pytest.mark.integration
def test_subscribe_sample_caps_excessive_request(opcua_server):
    """An over-large request is capped server-side, never unbounded."""
    out = ops.subscribe_sample(
        _target(opcua_server["url"]), opcua_server["temp"],
        samples=10_000, interval_ms=10, timeout_s=2,
    )
    assert out["requested_samples"] <= ops.MAX_SAMPLES


@pytest.mark.integration
def test_read_alarms_surfaces_motorfault(opcua_server):
    out = ops.read_alarms(_target(opcua_server["url"]), node_id="i=85", depth=3)
    names = {a["browse_name"] for a in out["active_alarms"]}
    assert "MotorFault" in names
    assert out["active_count"] >= 1


@pytest.mark.integration
def test_health_summary_thresholds_real(opcua_server):
    target = _target(opcua_server["url"])
    thresholds = {opcua_server["temp"]: {"warn_high": 70, "alarm_high": 90, "label": "temp"}}
    out = analysis.health_summary(target, [opcua_server["temp"]], thresholds)
    assert out["overall"] == "warn"  # 85 >= warn_high 70, < alarm_high 90
    assert out["counts"]["warn"] == 1
    assert out["offenders"][0]["status"] == "warn"


@pytest.mark.integration
def test_read_history_real(opcua_server):
    """HDA against the real in-process server (temp node is historized)."""
    from datetime import datetime, timedelta

    end = datetime.now() + timedelta(minutes=1)  # noqa: DTZ005 — server-local window
    start = end - timedelta(hours=1)
    out = ops.read_history(
        _target(opcua_server["url"]), opcua_server["temp"],
        start=start.isoformat(), end=end.isoformat(), max_points=50,
    )
    assert out["node_id"] == opcua_server["temp"]
    if opcua_server["history_ok"]:
        assert out["supported"] is True
        # The three set_value calls were recorded as history points.
        assert out["count"] >= 1
        assert all("source_timestamp" in v for v in out["values"])
    else:  # pragma: no cover — only when this asyncua build lacks sync historizing
        assert "supported" in out


@pytest.mark.integration
def test_monitor_changes_bounded_real(opcua_server):
    """CoV monitor against the real server: a static node yields one change."""
    from iaiops.core.brain import monitor

    out = monitor.monitor_changes(
        _target(opcua_server["url"]), opcua_server["press"],
        duration_s=2, interval_ms=100, max_changes=10,
    )
    assert out["ref"] == opcua_server["press"]
    # First read is always a change; a static value yields exactly one.
    assert out["change_count"] >= 1
    assert out["changes"][0]["value"] == 4.2
    assert out["change_count"] <= 10  # bounded by max_changes


@pytest.mark.integration
def test_anomaly_scan_stats_real(opcua_server):
    out = analysis.anomaly_scan(
        _target(opcua_server["url"]), opcua_server["temp"],
        samples=5, interval_ms=20,
    )
    assert out["samples"] >= 2
    assert out["mean"] == 85.0
    assert out["stddev"] == 0.0
    assert out["outlier_count"] == 0
