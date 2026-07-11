"""InfluxDB sink — line-protocol shaping + v1/v2 endpoint selection (fake requests, no server)."""

import sys
import types

import pytest

from iaiops.core.sink.base import SinkError, get_sink, normalize_points
from iaiops.core.sink.influxdb import InfluxDBSink


def _fake_requests(capture: dict, status: int = 204, text: str = "") -> types.ModuleType:
    mod = types.ModuleType("requests")

    class _ReqError(Exception):
        pass

    class Resp:
        def __init__(self) -> None:
            self.status_code = status
            self.text = text

    def post(url, params=None, headers=None, data=None, timeout=None):
        capture.update(url=url, params=params, headers=headers, data=data)
        return Resp()

    mod.RequestException = _ReqError
    mod.post = post
    return mod


@pytest.mark.unit
def test_v2_line_protocol(monkeypatch):
    cap: dict = {}
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(cap))
    sink = InfluxDBSink(url="http://h:8086", token="T", org="O", bucket="B")
    pts = normalize_points(
        [{"ref": "temp", "value": 21.5, "timestamp": "2026-07-11T00:00:00Z", "quality": "good"}]
    )
    assert sink.write(pts) == 1
    assert cap["url"].endswith("/api/v2/write")
    assert cap["params"]["bucket"] == "B"
    assert cap["headers"]["Authorization"] == "Token T"
    body = cap["data"].decode()
    assert body.startswith("temp")
    assert "value=21.5" in body
    assert ",quality=good" in body


@pytest.mark.unit
def test_v1_endpoint_and_skip_nonnumeric(monkeypatch):
    cap: dict = {}
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(cap))
    sink = InfluxDBSink(url="http://h:8086", database="mydb")
    pts = normalize_points([{"ref": "a", "value": "OPEN"}, {"ref": "b", "value": 3.0}])
    assert sink.write(pts) == 1  # only the numeric point
    assert cap["url"].endswith("/write")
    assert cap["params"]["db"] == "mydb"


@pytest.mark.unit
def test_http_error_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", _fake_requests({}, status=500, text="boom"))
    sink = InfluxDBSink(database="d")
    with pytest.raises(SinkError):
        sink.write(normalize_points([{"ref": "a", "value": 1.0}]))


@pytest.mark.unit
def test_get_sink_influxdb():
    assert isinstance(get_sink("influxdb", database="d"), InfluxDBSink)


@pytest.mark.unit
def test_escaping_spaces_in_metric(monkeypatch):
    cap: dict = {}
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(cap))
    InfluxDBSink(database="d").write(normalize_points([{"ref": "tank level", "value": 1.0}]))
    assert "tank\\ level" in cap["data"].decode()
