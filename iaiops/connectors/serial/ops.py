"""Serial ASCII instruments: the link, the read semantics, the session (HLD §17.4).

Two transports, one frame: a local serial port (pyserial — RS-232 / RS-485 /
RS-422 / USB virtual COM) or a serial device server's raw TCP socket. The safety
rules live here, on the code path every read takes:

* **The port is opened exclusively (D53).** pyserial ``exclusive=True`` takes an
  advisory lock; a port another program has locked is refused with a teaching
  error and never retried. A program that opened the port WITHOUT locking cannot
  be detected — the lock is advisory (待核实 per OS / driver).
* **Poll sends only the profile's query, and only on a dedicated bus (D54/D57).**
  A shared RS-485 bus already has a master; talking on it collides with the
  plant's own polling. The endpoint must say ``bus: dedicated`` — no default.
* **Listen needs ``stale_after_s`` (D55).** A silent instrument and an unchanging
  reading look the same on the wire; past ``stale_after_s`` with no line, there
  is no reading — never the last value.

Reads take a ``ch:<name>`` ref through the endpoint's sensor profile; a line that
does not decode is a gap with its reason (``InvalidReadingError``).
"""

from __future__ import annotations

import socket
import time
from contextlib import contextmanager
from typing import Any

from iaiops.connectors.serial.frames import LineFramer, decode_line
from iaiops.core.runtime.sensor import InvalidReadingError
from iaiops.core.runtime.session_factory import OTConnectionError, OTNoReadingError

CHANNEL_PREFIX = "ch:"
#: How long one non-blocking drain waits for bytes, in seconds.
DRAIN_WAIT_S = 0.05
MAX_SNIFF_SECONDS = 30.0
MAX_SNIFF_LINES = 200


# ── profile / ref ────────────────────────────────────────────────────────────


def _profile(target: Any) -> Any:
    from iaiops.core.runtime.sensor import binding

    profile = binding.endpoint_profile(target)
    if profile is None:
        raise ValueError(
            f"Serial endpoint {getattr(target, 'name', '?')!r} has no sensor_profile — a serial "
            "line is not decoded without one (`iaiops serial sniff` shows the raw lines to "
            "write it from)."
        )
    return profile


def channel_for(target: Any, ref: str) -> Any:
    """Resolve ``ch:<name>`` through the endpoint's profile, or refuse."""
    text = str(ref or "").strip()
    if not text.startswith(CHANNEL_PREFIX):
        raise ValueError(f"Serial ref {ref!r}: use ch:<channel> from the endpoint's profile.")
    try:
        return _profile(target).channel(text[len(CHANNEL_PREFIX) :])
    except KeyError as exc:
        raise ValueError(str(exc.args[0])) from exc


def _check_terms(target: Any, profile: Any) -> None:
    if profile.mode == "poll" and str(getattr(target, "bus", "") or "") != "dedicated":
        raise ValueError(
            f"Serial endpoint {getattr(target, 'name', '?')!r} would send a poll query, but it "
            "does not declare `bus: dedicated`. On a shared RS-485 bus the plant's master is "
            "already talking; a query would collide with it. Declare the bus, or use a "
            "listen-mode profile."
        )
    if profile.mode == "listen" and not float(getattr(target, "stale_after_s", 0) or 0) > 0:
        raise ValueError(
            f"Serial endpoint {getattr(target, 'name', '?')!r} listens, so it needs "
            "stale_after_s — how long a line stays a reading. There is no default."
        )


# ── the link ─────────────────────────────────────────────────────────────────


class SerialLink:
    """A local serial port (exclusive) or a raw TCP socket, read in short drains."""

    def __init__(self, target: Any) -> None:
        self._target = target
        self._port: Any = None
        self._sock: socket.socket | None = None

    def open(self) -> SerialLink:
        target = self._target
        path = str(getattr(target, "serial_port", "") or "")
        if path:
            self._open_serial(path)
        elif getattr(target, "host", ""):
            self._open_tcp(str(target.host), int(getattr(target, "port", 0) or 0))
        else:
            raise ValueError(
                f"Serial endpoint {getattr(target, 'name', '?')!r} needs serial_port "
                "(e.g. /dev/ttyUSB0, COM3) or host/port of a serial device server."
            )
        return self

    def _open_serial(self, path: str) -> None:
        try:
            import serial  # pyserial
        except ImportError as exc:  # pragma: no cover — the extra pulls it
            raise OTConnectionError(
                "pyserial is not installed — `pip install iaiops[sensor]`.", protocol="serial"
            ) from exc
        t = self._target
        try:
            self._port = serial.Serial(
                path,
                baudrate=int(getattr(t, "baudrate", 9600) or 9600),
                bytesize=int(getattr(t, "bytesize", 8) or 8),
                parity=str(getattr(t, "parity", "N") or "N"),
                stopbits=int(getattr(t, "stopbits", 1) or 1),
                timeout=DRAIN_WAIT_S,
                exclusive=True,
            )
        except serial.SerialException as exc:
            text = str(exc)
            if "lock" in text.lower() or "busy" in text.lower():
                raise OTConnectionError(
                    f"Serial port {path} is in use by another program — not taken from it "
                    "(the plant's own software may depend on it).",
                    protocol="serial",
                ) from exc
            raise OTConnectionError(
                f"Cannot open serial port {path}: {text}", protocol="serial"
            ) from exc

    def _open_tcp(self, host: str, port: int) -> None:
        if not port:
            raise ValueError("A serial device server needs its TCP port.")
        try:
            self._sock = socket.create_connection(
                (host, port), timeout=float(getattr(self._target, "timeout_s", 5) or 5)
            )
        except OSError as exc:
            raise OTConnectionError(
                f"Cannot reach the serial device server {host}:{port}: {exc}", protocol="serial"
            ) from exc
        self._sock.settimeout(DRAIN_WAIT_S)

    def read(self) -> bytes:
        """Whatever arrives within one short drain (possibly nothing)."""
        if self._port is not None:
            return bytes(self._port.read(4096))
        try:
            data = self._sock.recv(4096) if self._sock else b""
        except TimeoutError:
            return b""
        if data == b"" and self._sock is not None:
            raise OTConnectionError(
                "The serial device server closed the connection.", protocol="serial"
            )
        return data

    def write(self, data: bytes) -> None:
        if self._port is not None:
            self._port.write(data)
        elif self._sock is not None:
            self._sock.sendall(data)

    def close(self) -> None:
        for closer in (self._port, self._sock):
            if closer is not None:
                try:
                    closer.close()
                except OSError:
                    pass
        self._port = self._sock = None


# ── one-shot read ────────────────────────────────────────────────────────────


def _framer(profile: Any) -> LineFramer:
    f = profile.framing
    return LineFramer(terminator=f.terminator, encoding=f.encoding, max_line=f.max_line)


def _decode(channel: Any, line: str | None, reason: str) -> Any:
    if line is None:
        raise InvalidReadingError(f"{channel.name}: {reason}")
    return decode_line(channel, line)


def read_value(target: Any, ref: str) -> float | int:
    """Read one point once. Listen: the latest line within ``stale_after_s``; poll:
    the answer to the profile's query within ``timeout_s``."""
    channel = channel_for(target, ref)
    profile = _profile(target)
    _check_terms(target, profile)
    window = (
        float(target.stale_after_s)
        if profile.mode == "listen"
        else float(getattr(target, "timeout_s", 5) or 5)
    )
    link = SerialLink(target).open()
    try:
        framer = _framer(profile)
        if profile.mode == "poll":
            link.write(profile.query.encode("ascii"))
        latest: tuple[str | None, str] | None = None
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            lines = framer.feed(link.read())
            if lines:
                latest = lines[-1]
                if profile.mode == "poll":
                    break
    finally:
        link.close()
    if latest is None:
        raise OTNoReadingError(
            f"Serial {ref}: no line within {window:g} s "
            + ("(stale_after_s)." if profile.mode == "listen" else "(timeout_s)."),
            protocol="serial",
        )
    return _decode(channel, *latest).value


def sniff(target: Any, seconds: float = 5.0, max_lines: int = 20) -> dict[str, Any]:
    """[READ] Listen and return raw lines — sends nothing, needs no profile."""
    seconds = max(0.1, min(float(seconds), MAX_SNIFF_SECONDS))
    max_lines = max(1, min(int(max_lines), MAX_SNIFF_LINES))
    profile = None
    try:
        from iaiops.core.runtime.sensor import binding

        profile = binding.endpoint_profile(target)
    except (OSError, ValueError):
        profile = None
    framing = profile.framing if profile is not None and profile.framing else None
    framer = LineFramer(
        terminator=framing.terminator if framing else "\r\n",
        encoding="latin-1",  # show every byte; decoding is the profile's job
        max_line=framing.max_line if framing else 1024,
    )
    link = SerialLink(target).open()
    lines: list[str] = []
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(lines) < max_lines:
            for line, reason in framer.feed(link.read()):
                lines.append(line if line is not None else f"<{reason}>")
    finally:
        link.close()
    return {
        "endpoint": str(getattr(target, "name", "")),
        "seconds": seconds,
        "lines": lines[:max_lines],
        "note": "Raw lines (latin-1, so every byte shows). Nothing was sent to the instrument.",
    }


# ── session (collection) ─────────────────────────────────────────────────────


class SerialSession:
    """One held link; each read drains new lines and keeps the latest per channel."""

    def __init__(self, target: Any) -> None:
        self.target = target
        self.profile = _profile(target)
        _check_terms(target, self.profile)
        self.link = SerialLink(target)
        self.framer = _framer(self.profile)
        self.latest: tuple[str | None, str] | None = None
        self.latest_at = 0.0
        self.opened_at = 0.0

    def drain(self) -> None:
        for line in self.framer.feed(self.link.read()):
            self.latest, self.latest_at = line, time.monotonic()


@contextmanager
def serial_session(target: Any):
    session = SerialSession(target)
    session.link.open()
    session.opened_at = time.monotonic()
    try:
        yield session
    finally:
        session.link.close()


def session_read(session: SerialSession, ref: str) -> tuple[Any, str]:
    """Collection read on a held link. Stale or undecodable → no reading (a gap)."""
    channel = channel_for(session.target, ref)
    profile = session.profile
    if profile.mode == "poll":
        session.link.write(profile.query.encode("ascii"))
        deadline = time.monotonic() + float(getattr(session.target, "timeout_s", 5) or 5)
        asked = time.monotonic()
        while time.monotonic() < deadline and session.latest_at < asked:
            session.drain()
        if session.latest_at < asked:
            raise OTNoReadingError(f"Serial {ref}: no answer to the query.", protocol="serial")
    else:
        stale = float(session.target.stale_after_s)
        session.drain()
        if session.latest is None:
            # Nothing yet since the link opened: give the first line the same
            # window any line gets, rather than calling a just-opened link stale.
            deadline = session.opened_at + stale
            while session.latest is None and time.monotonic() < deadline:
                session.drain()
            if session.latest is None:
                raise OTNoReadingError(
                    f"Serial {ref}: no line within {stale:g} s since the link opened.",
                    protocol="serial",
                )
        age = time.monotonic() - session.latest_at
        if age > stale:
            raise OTNoReadingError(
                f"Serial {ref}: no line for {age:.1f} s — stale (stale_after_s "
                f"{float(session.target.stale_after_s):g}).",
                protocol="serial",
            )
    try:
        return _decode(channel, *session.latest).value, ""
    except InvalidReadingError as exc:
        raise OTNoReadingError(f"Serial {ref}: {exc}", protocol="serial") from exc


__all__ = [
    "SerialLink",
    "SerialSession",
    "channel_for",
    "read_value",
    "serial_session",
    "session_read",
    "sniff",
]
