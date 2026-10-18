"""Defects an adversarial review of E4 found — most of them stale or wrong values.

1. Listen sessions stored buffered lines as fresh (one 4 KB chunk per tick,
   stamped at drain time): old data — even from a silent instrument — as new.
2. Poll accepted a late / already-waiting reply as the current answer.
3. A partial first line after open decoded as a value ("2.50" of "12.50").
4. An optional `value` group crashed with TypeError; float() accepted "1_000".
5. A silent instrument on a one-shot read was "reachable".
6. A TCP endpoint without a port silently got 4840; serial_port without a
   baudrate silently got 19200.
7. A non-ASCII terminator loaded, then crashed at read time.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from iaiops.connectors.serial import ops
from iaiops.connectors.serial.frames import LineFramer, decode_line
from iaiops.core.runtime.sensor import InvalidReadingError, parse_profile
from iaiops.core.runtime.session_factory import OTConnectionError, OTNoReadingError

pytestmark = [pytest.mark.unit, pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX")]

LINE = r"(?P<value>[+-]?\d+\.\d+) (?P<unit>kg)"


def _profile(mode="listen", query=None, pattern=LINE):
    raw = {
        "id": "scale",
        "protocol": "serial",
        "source": "manual",
        "verified": "待核实",
        "framing": {"terminator": "\r\n", "encoding": "ascii", "max_line": 64},
        "mode": mode,
        "channels": [
            {"name": "w", "layout": {"pattern": pattern}, "unit": "kg", "signal": "level"}
        ],
    }
    if query:
        raw["query"] = query
    return parse_profile(raw)


@pytest.fixture
def pty_port():
    controller, device = os.openpty()
    yield controller, os.ttyname(device)
    for fd in (controller, device):
        try:
            os.close(fd)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _lookup(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.endpoint_profile", lambda t: t._profile)


def _target(profile, path, **extra):
    return SimpleNamespace(
        name="s", protocol="serial", serial_port=path, host="", port=0, baudrate=9600,
        bytesize=8, parity="N", stopbits=1, timeout_s=1.0,
        stale_after_s=extra.pop("stale_after_s", 1.0), bus=extra.pop("bus", ""),
        sensor_profile="p.yaml", _profile=profile, **extra,
    )  # fmt: skip


def test_1_a_session_reports_the_newest_line_even_after_a_burst(pty_port):
    controller, path = pty_port
    with ops.serial_session(_target(_profile(), path)) as session:
        time.sleep(0.1)
        os.write(controller, b"".join(f"{i}.00 kg\r\n".encode() for i in range(1000)))
        time.sleep(0.6)
        value, _ = ops.session_read(session, "ch:w")
    assert value == pytest.approx(999.0)


def test_1_a_session_does_not_pass_off_an_old_line_as_fresh(pty_port):
    controller, path = pty_port
    with ops.serial_session(_target(_profile(), path, stale_after_s=0.4)) as session:
        time.sleep(0.1)
        os.write(controller, b"6.00 kg\r\n7.00 kg\r\n")
        time.sleep(0.8)  # the instrument went quiet after that line
        with pytest.raises(OTNoReadingError, match="stale"):
            ops.session_read(session, "ch:w")


class _FakeTcp:
    """A link whose input already holds a stale reply, then answers each query."""

    def __init__(self, waiting: bytes, answers: list[bytes]):
        self.buffer = waiting
        self.answers = answers
        self.written: list[bytes] = []

    def open(self):
        return self

    def read(self):
        data, self.buffer = self.buffer, b""
        return data

    def flush_input(self):
        self.buffer = b""

    def write(self, data):
        self.written.append(data)
        if self.answers:
            self.buffer += self.answers.pop(0)

    def close(self):
        pass


def test_2_poll_takes_the_answer_to_this_query_not_a_waiting_reply(monkeypatch):
    fake = _FakeTcp(b"9.00 kg\r\n", [b"10.00 kg\r\n"])
    monkeypatch.setattr(ops, "SerialLink", lambda target: fake)
    target = _target(_profile("poll", "P\r\n"), "", bus="dedicated")
    assert ops.read_value(target, "ch:w") == pytest.approx(10.0)
    assert fake.written == [b"P\r\n"]


def test_2_a_held_poll_link_flushes_a_late_reply_before_each_query(monkeypatch):
    fake = _FakeTcp(b"", [b"10.00 kg\r\n", b"11.00 kg\r\n"])
    monkeypatch.setattr(ops, "SerialLink", lambda target: fake)
    target = _target(_profile("poll", "P\r\n"), "", bus="dedicated")
    with ops.serial_session(target) as session:
        assert ops.session_read(session, "ch:w")[0] == pytest.approx(10.0)
        fake.buffer += b"9.00 kg\r\n"  # a late reply that arrived between ticks
        time.sleep(ops.POLL_REUSE_S + 0.05)
        assert ops.session_read(session, "ch:w")[0] == pytest.approx(11.0)
    assert fake.written == [b"P\r\n", b"P\r\n"]


def test_3_a_partial_first_line_is_dropped():
    framer = LineFramer(terminator="\r\n", encoding="ascii", max_line=64, synced=False)
    assert framer.feed(b"2.50 kg\r\n12.60 kg\r\n") == [("12.60 kg", "")]


def test_3_a_one_shot_read_never_decodes_the_fragment(pty_port):
    controller, path = pty_port

    def write():
        time.sleep(0.2)
        os.write(controller, b"2.50 kg\r\n")  # tail of a line the open landed in
        time.sleep(0.1)
        os.write(controller, b"12.60 kg\r\n")

    threading.Thread(target=write, daemon=True).start()
    assert ops.read_value(_target(_profile(), path), "ch:w") == pytest.approx(12.6)


@pytest.mark.parametrize(
    ("pattern", "line"), [(r"(?P<value>\d+\.\d+)? kg", " kg"), (r"(?P<value>\S+) kg", "1_000 kg")]
)
def test_4_a_missing_or_non_numeric_value_is_a_refusal(pattern, line):
    channel = _profile(pattern=pattern).channel("w")
    with pytest.raises(InvalidReadingError):
        decode_line(channel, line)


def test_5_a_silent_instrument_on_a_one_shot_read_is_not_reachable(pty_port):
    _, path = pty_port
    with pytest.raises(OTConnectionError) as excinfo:
        ops.read_value(_target(_profile(), path, stale_after_s=0.3), "ch:w")
    assert not isinstance(excinfo.value, OTNoReadingError)
    assert "heard nothing" in str(excinfo.value)


def test_6_serial_needs_an_explicit_tcp_port_and_baudrate():
    from iaiops.core.runtime.config import _parse_target

    with pytest.raises(ValueError, match="port"):
        _parse_target({"name": "s", "protocol": "serial", "host": "10.0.0.5"})
    with pytest.raises(ValueError, match="baudrate"):
        _parse_target({"name": "s", "protocol": "serial", "serial_port": "/dev/ttyUSB0"})
    ok = _parse_target(
        {"name": "s", "protocol": "serial", "serial_port": "/dev/ttyUSB0", "baudrate": 9600}
    )
    assert ok.baudrate == 9600


def test_6_bus_is_serial_only():
    from iaiops.core.runtime.config import _parse_target

    with pytest.raises(ValueError, match="bus"):
        _parse_target({"name": "m", "protocol": "modbus", "host": "h", "bus": "shared"})


def test_7_a_non_ascii_terminator_is_refused_at_load():
    raw = {
        "id": "x", "protocol": "serial", "source": "manual", "verified": "待核实",
        "framing": {"terminator": "µ"}, "mode": "listen",
        "channels": [{"name": "w", "layout": {"pattern": LINE}, "unit": "kg", "signal": "level"}],
    }  # fmt: skip
    with pytest.raises(ValueError, match="ASCII"):
        parse_profile(raw)


def test_a_channel_without_a_fixed_unit_is_refused_at_load():
    raw = {
        "id": "x", "protocol": "serial", "source": "manual", "verified": "待核实", "mode": "listen",
        "channels": [
            {"name": "w", "layout": {"pattern": LINE}, "unit_from": "unit", "signal": "level"}
        ],
    }  # fmt: skip
    with pytest.raises(ValueError, match="fixed unit"):
        parse_profile(raw)


def test_readiness_judges_serial_endpoints(monkeypatch):
    from iaiops.core.readiness.sensors import sensor_point_facts

    target = SimpleNamespace(
        name="s", protocol="serial", sensor_profile="p.yaml", port_profiles=(), stale_after_s=1,
        tags=(SimpleNamespace(ref="weight"),), _profile=_profile(),
    )  # fmt: skip
    monkeypatch.setattr(
        "iaiops.core.runtime.sensor.binding.cached_profile", lambda path: _profile()
    )
    facts = sensor_point_facts((target,))
    assert facts["judged_endpoints"] == 1 and facts["unreadable"]
    assert "scale" in facts["unverified_profiles"]


def test_doctor_does_not_count_serial_as_a_failure():
    from iaiops.core.runtime.capabilities import PROBE_HARD, REGISTRY, UNSUPPORTED

    cap = REGISTRY["serial"]
    assert cap.doctor_probe is not UNSUPPORTED or cap.probe_style != PROBE_HARD
