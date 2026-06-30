"""BACnet/IP ops tests against a MOCKED BAC0 network.

BAC0/bacpypes3 needs a live BACnet/IP segment, so ``_build_bacnet_network`` is
monkeypatched to return a fake network whose who_is()/read() duck-type the BAC0
surface — exercising discovery, object-list browse, property read, and the
present-value points sweep (with per-point error tolerance) without any gear.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.bacnet import ops
from iaiops.core.runtime.config import TargetConfig


class _FakeTimestamp:
    def __init__(self, date: str, time: str) -> None:
        self.date = date
        self.time = time


class _FakeDatum:
    def __init__(self, value: float) -> None:
        self.realValue = value


class _FakeLogRecord:
    """Duck-types a bacpypes3 TrendLog log record (timestamp + logDatum CHOICE)."""

    def __init__(self, date: str, time: str, value: float) -> None:
        self.timestamp = _FakeTimestamp(date, time)
        self.logDatum = _FakeDatum(value)


class _FakeNet:
    def __init__(self):
        self.disconnected = False
        self._objects = [
            ("analogInput", 1), ("analogValue", 2), ("binaryInput", 3),
            ("device", 1001), ("notificationClass", 9),  # filtered out of points
        ]
        self._values = {
            "192.168.1.10 analogInput 1 presentValue": 21.5,
            "192.168.1.10 analogValue 2 presentValue": 1013.0,
            "192.168.1.10 binaryInput 3 presentValue": "active",
        }
        # COV machinery: a registry keyed by task id (mirrors BAC0._running_cov_tasks).
        self._cov_tasks: dict[int, dict] = {}
        self._next_cov_id = 100
        self.cov_fire: list[tuple[str, object]] = []  # (property, value) to emit on subscribe
        self.cancelled: list[int] = []
        self.cov_calls: list[dict] = []
        # TrendLog buffer returned by readRange.
        self.trend_records = [
            _FakeLogRecord("2026-06-30", "12:00:00", 21.5),
            _FakeLogRecord("2026-06-30", "12:10:00", 21.8),
        ]
        self.range_calls: list[dict] = []

    def who_is(self, *args, **kwargs):
        return [(1001, "192.168.1.10"), (1002, "192.168.1.11")]

    def read(self, request):
        if request.endswith("objectList"):
            return list(self._objects)
        if request in self._values:
            return self._values[request]
        raise ValueError(f"unknown object: {request}")

    @property
    def cov_tasks(self):
        return self._cov_tasks

    def cov(self, address, objectID, lifetime=900, confirmed=False, callback=None):  # noqa: N803 — mirrors BAC0.lite.cov
        task_id = self._next_cov_id
        self._next_cov_id += 1
        self._cov_tasks[task_id] = {"address": address, "objectID": objectID}
        self.cov_calls.append(
            {"address": address, "objectID": objectID, "lifetime": lifetime,
             "confirmed": confirmed}
        )
        if callback is not None:
            for prop, value in self.cov_fire:
                callback(prop, value)
        return task_id

    def cancel_cov(self, task_id):
        self.cancelled.append(task_id)
        self._cov_tasks.pop(task_id, None)

    def readRange(self, args, range_params=None, **kwargs):  # noqa: N802 — mirrors BAC0.lite.readRange
        self.range_calls.append({"args": args, "range_params": range_params})
        return list(self.trend_records)

    def disconnect(self):
        self.disconnected = True


@pytest.fixture
def bac(monkeypatch):
    net = _FakeNet()
    monkeypatch.setattr(conn, "_build_bacnet_network", lambda target: net)
    target = TargetConfig(name="ahu-net", protocol="bacnet", host="192.168.1.5")
    return target, net


@pytest.mark.unit
def test_discover(bac):
    target, _ = bac
    out = ops.bacnet_discover(target)
    assert out["device_count"] == 2
    d0 = out["devices"][0]
    assert d0["device_id"] == 1001
    assert d0["address"] == "192.168.1.10"


@pytest.mark.unit
def test_discover_disconnects(bac):
    target, net = bac
    ops.bacnet_discover(target)
    assert net.disconnected is True


@pytest.mark.unit
def test_object_list(bac):
    target, _ = bac
    out = ops.bacnet_object_list(target, "192.168.1.10", 1001)
    assert out["object_count"] == 5
    assert {"object_type": "analogInput", "instance": 1} in out["objects"]


@pytest.mark.unit
def test_object_list_requires_args(bac):
    target, _ = bac
    assert "error" in ops.bacnet_object_list(target, "", 1001)


@pytest.mark.unit
def test_read_property(bac):
    target, _ = bac
    out = ops.bacnet_read_property(target, "192.168.1.10", "analogInput", 1)
    assert out["value"] == 21.5
    assert out["property"] == "presentValue"


@pytest.mark.unit
def test_read_property_requires_args(bac):
    target, _ = bac
    assert "error" in ops.bacnet_read_property(target, "192.168.1.10", "", 1)


@pytest.mark.unit
def test_read_points_filters_readable_types(bac):
    target, _ = bac
    out = ops.bacnet_read_points(target, "192.168.1.10", 1001)
    # 3 readable (analogInput/analogValue/binaryInput); device + notificationClass skipped.
    assert out["point_count"] == 3
    assert out["skipped_non_readable"] == 2
    ai = next(p for p in out["points"] if p["object_type"] == "analogInput")
    assert ai["present_value"] == 21.5


@pytest.mark.unit
def test_read_points_tolerates_per_point_error(monkeypatch, bac):
    target, net = bac

    def flaky_read(request):
        if "analogValue 2 presentValue" in request:
            raise ValueError("timeout")
        if request.endswith("objectList"):
            return list(net._objects)
        return net._values.get(request, 0)

    monkeypatch.setattr(net, "read", flaky_read)
    out = ops.bacnet_read_points(target, "192.168.1.10", 1001)
    errored = [p for p in out["points"] if "error" in p]
    assert len(errored) == 1
    assert out["point_count"] == 3  # the sweep still completes


@pytest.mark.unit
def test_wrong_protocol_guarded():
    target = TargetConfig(name="x", protocol="modbus", host="1.2.3.4")
    with pytest.raises(conn.OTConnectionError, match="not bacnet"):
        with conn.bacnet_session(target):
            pass


@pytest.mark.unit
def test_cov_subscribe_collects_up_to_max(bac):
    target, net = bac
    net.cov_fire = [("presentValue", 21.5), ("presentValue", 22.0), ("presentValue", 22.5)]
    out = ops.bacnet_cov_subscribe(
        target, "192.168.1.10", "analogInput", 1, max_notifications=2, timeout_s=5,
    )
    assert out["notification_count"] == 2  # capped at max, not all 3
    assert out["terminated_reason"] == "max_notifications"
    assert out["changes"][0]["value"] == 21.5


@pytest.mark.unit
def test_cov_subscribe_terminates_on_timeout(bac):
    target, net = bac
    net.cov_fire = []  # no notifications ever arrive
    out = ops.bacnet_cov_subscribe(
        target, "192.168.1.10", "analogInput", 1, max_notifications=10, timeout_s=1,
    )
    # The capture MUST terminate even when nothing arrives (bounded by timeout).
    assert out["notification_count"] == 0
    assert out["terminated_reason"] == "timeout"


@pytest.mark.unit
def test_cov_subscribe_always_unsubscribes(bac):
    target, net = bac
    net.cov_fire = [("presentValue", 1.0)]
    ops.bacnet_cov_subscribe(
        target, "192.168.1.10", "analogInput", 1, max_notifications=1, timeout_s=5,
    )
    # Every subscription created during the capture must be cancelled (no leak).
    assert net.cancelled == [100]
    assert net.cov_tasks == {}


@pytest.mark.unit
def test_cov_subscribe_passes_objectid_tuple(bac):
    target, net = bac
    net.cov_fire = [("presentValue", 1.0)]
    ops.bacnet_cov_subscribe(
        target, "192.168.1.10", "analogValue", 7, max_notifications=1, timeout_s=5,
    )
    assert net.cov_calls[0]["objectID"] == ("analogValue", 7)


@pytest.mark.unit
def test_cov_subscribe_requires_args(bac):
    target, _ = bac
    assert "error" in ops.bacnet_cov_subscribe(target, "", "analogInput", 1)


@pytest.mark.unit
def test_read_trend_log(bac):
    target, _ = bac
    out = ops.bacnet_read_trend_log(target, "192.168.1.10", 1, count=50)
    assert out["record_count"] == 2
    assert out["records"][0]["value"] == 21.5
    assert out["records"][0]["timestamp"] == "2026-06-30 12:00:00"


@pytest.mark.unit
def test_read_trend_log_builds_logbuffer_request(bac):
    target, net = bac
    ops.bacnet_read_trend_log(target, "192.168.1.10", 5, count=10, newest_first=True)
    call = net.range_calls[0]
    assert call["args"] == "192.168.1.10 trendLog 5 logBuffer"
    # RangeByPosition; newest_first reverses the search via a negative count.
    assert call["range_params"][0] == "p"
    assert call["range_params"][-1] == -10


@pytest.mark.unit
def test_read_trend_log_requires_args(bac):
    target, _ = bac
    assert "error" in ops.bacnet_read_trend_log(target, "", 1)


@pytest.mark.unit
def test_construction_bind_error_is_translated(monkeypatch):
    # BAC0.lite(ip=...) binds UDP/47808 in the builder; a bind failure must be
    # translated to a teaching OTConnectionError, not raised raw.
    def boom(target):
        raise OSError("address already in use")

    monkeypatch.setattr(conn, "_build_bacnet_network", boom)
    target = TargetConfig(name="ahu-net", protocol="bacnet", host="192.168.1.5")
    with pytest.raises(conn.OTConnectionError, match="BACNET operation"):
        ops.bacnet_discover(target)
