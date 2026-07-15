"""Timestamped OPC-UA A&C alarm events — real-server roundtrip + parsing + RCA wiring.

The integration test runs a REAL in-process ``asyncua.sync.Server`` with a
ConditionType event generator and drives ``ops.alarm_events`` end-to-end
(subscription → ConditionRefresh → event with the server's own Time). The rest
is pure: event-field parsing and the rca_collect timed-first/scan-fallback wiring.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

import pytest

from iaiops.connectors.opcua import ops
from iaiops.connectors.opcua.ops import _parse_alarm_event
from iaiops.core.brain import rca_collect
from iaiops.core.runtime.config import TargetConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def condition_server():
    """Real asyncua server + a ConditionType event generator."""
    from asyncua import ua
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/aiops-ae"
    srv = Server()
    srv.set_endpoint(url)
    srv.set_server_name("iaiops-ae-test")
    evgen = srv.get_event_generator(ua.ObjectIds.ConditionType)
    srv.start()
    try:
        yield {"url": url, "evgen": evgen, "ua": ua}
    finally:
        srv.stop()


def _target(url: str) -> TargetConfig:
    return TargetConfig(name="line1", protocol="opcua", endpoint_url=url)


@pytest.mark.integration
def test_alarm_events_real_roundtrip(condition_server):
    """A triggered condition event arrives WITH the server's own timestamp."""
    import threading

    ua, evgen = condition_server["ua"], condition_server["evgen"]

    def _fire():
        evgen.event.Message = ua.LocalizedText("Motor overload trip")
        evgen.event.Severity = 700
        evgen.trigger()

    timer = threading.Timer(0.6, _fire)  # fire while alarm_events is listening
    timer.start()
    try:
        out = ops.alarm_events(_target(condition_server["url"]), duration_s=4, max_events=5)
    finally:
        timer.cancel()
    assert out["event_count"] >= 1
    event = out["events"][0]
    assert event["message"] == "Motor overload trip"
    assert event["severity"] == 700
    # The load-bearing property: the event carries the SERVER's Time.
    assert event["timestamp"], "A&C event must carry the server's event Time"
    datetime.fromisoformat(event["timestamp"])  # parses as ISO-8601
    # ConditionRefresh ran; this server retains nothing → BadNothingToDo == success.
    assert out["condition_refresh"] is True
    assert out["refresh_error"] == ""


class TestEventParsing:
    class _Localized:
        def __init__(self, text):
            self.Text = text

    def test_active_state_active_maps_to_active(self):
        event = type(
            "E",
            (),
            {
                "SourceName": "FIC101",
                "Message": self._Localized("high level"),
                "Severity": 500,
                "ActiveState": self._Localized("Active"),
                "Time": datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
            },
        )()
        parsed = _parse_alarm_event(event)
        assert parsed == {
            "source": "FIC101",
            "message": "high level",
            "severity": 500,
            "state": "ACTIVE",
            "timestamp": "2026-07-15T08:00:00+00:00",
        }

    def test_active_state_inactive_maps_to_rtn(self):
        event = type("E", (), {"ActiveState": self._Localized("Inactive")})()
        assert _parse_alarm_event(event)["state"] == "RTN"

    def test_retain_flag_used_when_no_active_state(self):
        assert _parse_alarm_event(type("E", (), {"Retain": True})())["state"] == "ACTIVE"
        assert _parse_alarm_event(type("E", (), {"Retain": False})())["state"] == "RTN"

    def test_plain_event_without_condition_state_is_event(self):
        parsed = _parse_alarm_event(type("E", (), {"Message": "boom"})())
        assert (parsed["state"], parsed["timestamp"]) == ("EVENT", None)


class TestFailedConnectThreadHygiene:
    def test_failed_connects_do_not_accumulate_threads(self):
        """Regression: asyncua's sync Client starts a non-daemon ThreadLoop in its
        CONSTRUCTOR, and make_session skips teardown on connect failure — before
        the _connect_opcua cleanup every failed connect leaked one running thread
        (enough to stop a long-lived process, or pytest, from ever exiting)."""
        import threading

        target = TargetConfig(
            name="dead", protocol="opcua", endpoint_url="opc.tcp://nonexistent.invalid:4840"
        )
        baseline = threading.active_count()
        for _ in range(3):
            with pytest.raises(Exception, match="."):
                ops.server_info(target)
        # One parked asyncio default-executor worker may legitimately remain;
        # what must NOT happen is one-leaked-ThreadLoop-per-attempt growth.
        assert threading.active_count() <= baseline + 1


class TestRcaCollectWiring:
    def _target(self):
        return TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://x:4840")

    def test_timed_path_wins_when_events_arrive(self, monkeypatch):
        timed = {
            "events": [
                {
                    "source": "FIC101",
                    "message": "high level",
                    "state": "ACTIVE",
                    "timestamp": "2026-07-15T08:00:00+00:00",
                }
            ]
        }
        monkeypatch.setattr(ops, "alarm_events", lambda t, duration_s, refresh: timed)
        events = rca_collect.collect_active_alarms(self._target())
        assert events[0]["timestamp"] == "2026-07-15T08:00:00+00:00"

    def test_falls_back_to_untimed_scan_when_no_events(self, monkeypatch):
        monkeypatch.setattr(ops, "alarm_events", lambda t, duration_s, refresh: {"events": []})
        monkeypatch.setattr(
            ops,
            "read_alarms",
            lambda t: {"active_alarms": [{"browse_name": "MotorFault", "value": True}]},
        )
        events = rca_collect.collect_active_alarms(self._target())
        assert events == [
            {
                "source": "MotorFault",
                "message": "MotorFault",
                "state": "ACTIVE",
                "timestamp": None,
            }
        ]

    def test_falls_back_when_timed_path_raises(self, monkeypatch):
        def _boom(t, duration_s, refresh):
            raise RuntimeError("no A&C support")

        monkeypatch.setattr(ops, "alarm_events", _boom)
        monkeypatch.setattr(
            ops,
            "read_alarms",
            lambda t: {"active_alarms": [{"browse_name": "PumpAlarm", "value": True}]},
        )
        events = rca_collect.collect_active_alarms(self._target())
        assert events[0]["source"] == "PumpAlarm"

    def test_non_opcua_targets_contribute_no_alarms(self):
        target = TargetConfig(name="plc", protocol="modbus", host="10.0.0.1")
        assert rca_collect.collect_active_alarms(target) == []
