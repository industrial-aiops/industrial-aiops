"""E4 (HLD §17.4): the serial link, read semantics and safety rules.

Self-test without hardware, two transports:
- a pty pair (os.openpty) opened by pyserial — the real serial code path;
- a local TCP socket — the serial-device-server path.
Rules pinned: the port is opened exclusively and a busy port is refused (D53);
poll mode sends only the profile's query and is refused unless the endpoint
declares `bus: dedicated` (D57); listen mode needs stale_after_s and a silent
instrument is a gap, not the last value (D55).
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from iaiops.connectors.serial import ops
from iaiops.core.runtime.sensor import InvalidReadingError, parse_profile
from iaiops.core.runtime.session_factory import OTConnectionError, OTNoReadingError

pytestmark = [pytest.mark.unit, pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX")]

LINE = r"(?P<status>ST|US|OL),(?P<kind>GS|NT),(?P<value>[+-]?\d+\.\d+)(?P<unit>kg|g)"


def _profile(mode="listen", query=None):
    raw = {
        "id": "scale",
        "protocol": "serial",
        "source": "manual",
        "verified": "待核实",
        "framing": {"terminator": "\r\n", "encoding": "ascii", "max_line": 64},
        "mode": mode,
        "channels": [
            {
                "name": "weight",
                "layout": {"pattern": LINE},
                "unit": "kg",
                "unit_from": "unit",
                "status": {
                    "field": "status",
                    "ok": ["ST"],
                    "invalid": {"US": "unstable", "OL": "overload"},
                },
                "signal": "level",
            }
        ],
    }
    if query:
        raw["query"] = query
    return parse_profile(raw)


@pytest.fixture
def pty_port():
    controller, device = os.openpty()
    path = os.ttyname(device)
    yield controller, path
    for fd in (controller, device):
        try:
            os.close(fd)
        except OSError:
            pass


def _target(profile, path="", host="", port=0, **extra):
    return SimpleNamespace(
        name="scale1",
        protocol="serial",
        serial_port=path,
        host=host,
        port=port,
        baudrate=9600,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout_s=2.0,
        stale_after_s=extra.pop("stale_after_s", 1.0),
        bus=extra.pop("bus", ""),
        sensor_profile="scale.yaml",
        _profile=profile,
        **extra,
    )


@pytest.fixture(autouse=True)
def _profile_lookup(monkeypatch):
    monkeypatch.setattr(
        "iaiops.core.runtime.sensor.binding.endpoint_profile", lambda target: target._profile
    )


def _stream(fd, lines, period=0.05, delay=0.2):
    """Write lines after ``delay`` — pyserial flushes input on open, as real ports do."""

    def run():
        time.sleep(delay)
        for line in lines:
            os.write(fd, line.encode() + b"\r\n")
            time.sleep(period)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


# ── listen over a real pty ───────────────────────────────────────────────────


def test_listen_reads_the_latest_stable_line(pty_port):
    controller, path = pty_port
    _stream(controller, ["ST,GS,+0001.00kg", "ST,GS,+0002.50kg"])
    value = ops.read_value(_target(_profile(), path=path), "ch:weight")
    assert value == pytest.approx(2.5)


def test_listen_an_unstable_latest_line_is_a_gap_not_the_previous_value(pty_port):
    controller, path = pty_port
    _stream(controller, ["ST,GS,+0001.00kg", "US,GS,+0001.20kg"])
    with pytest.raises(InvalidReadingError, match="unstable"):
        ops.read_value(_target(_profile(), path=path), "ch:weight")


def test_listen_a_silent_instrument_is_no_reading(pty_port):
    """Silence on a one-shot read: the device did not answer (not 'connected')."""
    _, path = pty_port
    started = time.monotonic()
    with pytest.raises(ops.SerialSilenceError, match="heard nothing"):
        ops.read_value(_target(_profile(), path=path, stale_after_s=0.3), "ch:weight")
    assert time.monotonic() - started < 2.0


def test_listen_without_stale_after_s_is_refused(pty_port):
    _, path = pty_port
    with pytest.raises(ValueError, match="stale_after_s"):
        ops.read_value(_target(_profile(), path=path, stale_after_s=0), "ch:weight")


def test_the_port_is_opened_exclusively_and_a_busy_one_refused(pty_port):
    import serial

    _, path = pty_port
    holder = serial.Serial(path, exclusive=True)
    try:
        with pytest.raises(OTConnectionError, match="in use"):
            ops.read_value(_target(_profile(), path=path), "ch:weight")
    finally:
        holder.close()


def test_sniff_returns_raw_lines_and_sends_nothing(pty_port):
    controller, path = pty_port
    # The first line after open is dropped (it may be the tail of a line).
    _stream(controller, ["warm-up", "ST,GS,+0001.00kg", "garbage"])
    out = ops.sniff(_target(_profile(), path=path), seconds=0.5, max_lines=10)
    assert out["lines"][:2] == ["ST,GS,+0001.00kg", "garbage"]
    os.set_blocking(controller, False)
    with pytest.raises(BlockingIOError):
        os.read(controller, 100)  # nothing was written to the instrument


# ── poll over TCP (serial device server) ─────────────────────────────────────


def _tcp_instrument(answer: bytes, expect: bytes):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    seen = []

    def run():
        conn, _ = server.accept()
        with conn:
            data = conn.recv(64)
            seen.append(data)
            if data == expect:
                conn.sendall(answer)
            time.sleep(0.3)
        server.close()

    threading.Thread(target=run, daemon=True).start()
    return server.getsockname()[1], seen


def test_poll_sends_exactly_the_profile_query_on_a_dedicated_bus():
    port, seen = _tcp_instrument(b"ST,NT,+0003.25kg\r\n", b"P\r\n")
    target = _target(_profile("poll", "P\r\n"), host="127.0.0.1", port=port, bus="dedicated")
    assert ops.read_value(target, "ch:weight") == pytest.approx(3.25)
    assert seen == [b"P\r\n"]


@pytest.mark.parametrize("bus", ["", "shared"])
def test_poll_is_refused_unless_the_bus_is_dedicated(bus):
    target = _target(_profile("poll", "P\r\n"), host="127.0.0.1", port=1, bus=bus)
    with pytest.raises(ValueError, match="dedicated"):
        ops.read_value(target, "ch:weight")


def test_a_ref_must_be_a_profile_channel():
    with pytest.raises(ValueError, match="ch:"):
        ops.read_value(_target(_profile(), path="/dev/null"), "weight")


# ── session (collection): one held link, latest line per channel ─────────────


def test_session_keeps_the_link_and_reports_staleness(pty_port):
    controller, path = pty_port
    target = _target(_profile(), path=path, stale_after_s=0.4)
    with ops.serial_session(target) as session:
        os.write(controller, b"warm-up\r\nST,GS,+0004.00kg\r\n")
        time.sleep(0.1)
        value, _ = ops.session_read(session, "ch:weight")
        assert value == pytest.approx(4.0)
        time.sleep(0.6)  # nothing new → stale
        with pytest.raises(OTNoReadingError, match="stale"):
            ops.session_read(session, "ch:weight")


def test_session_first_read_waits_for_the_first_line_instead_of_a_bogus_gap(pty_port):
    """Lab LAN run: the first read came 50 ms after opening the link, before any
    line, and was reported as 'no line for 312861 s' (time since boot)."""
    controller, path = pty_port
    target = _target(_profile(), path=path, stale_after_s=1.0)
    with ops.serial_session(target) as session:
        _stream(controller, ["warm-up", "ST,GS,+0005.00kg"], delay=0.2)
        value, _ = ops.session_read(session, "ch:weight")
        assert value == pytest.approx(5.0)


def test_session_silent_from_the_start_says_so_honestly(pty_port):
    _, path = pty_port
    target = _target(_profile(), path=path, stale_after_s=0.3)
    with ops.serial_session(target) as session:
        with pytest.raises(OTNoReadingError) as excinfo:
            ops.session_read(session, "ch:weight")
    message = str(excinfo.value)
    assert "since the link opened" in message and "312" not in message
