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
import threading
import time
from contextlib import contextmanager
from typing import Any

from iaiops.connectors.serial.frames import LineFramer, decode_line
from iaiops.core.runtime.sensor import DescriptionUnusableError, InvalidReadingError
from iaiops.core.runtime.session_factory import OTConnectionError, OTNoReadingError

CHANNEL_PREFIX = "ch:"
#: How long one non-blocking drain waits for bytes, in seconds.
DRAIN_WAIT_S = 0.05
MAX_SNIFF_SECONDS = 30.0
MAX_SNIFF_LINES = 200
#: Longest an input flush may run before a poll query (an idle device is empty
#: within one drain; a device that never stops talking is not a poll device).
FLUSH_LIMIT_S = 0.5
#: A poll answer is reused for the other channels of the same collection tick
#: rather than sending the query once per channel.
POLL_REUSE_S = 0.25


class SerialSilenceError(OTConnectionError):
    """The port opened but nothing was heard — cable, port, baud rate, or a silent
    instrument. Deliberately NOT an OTNoReadingError: the device did not answer."""


# ── profile / ref ────────────────────────────────────────────────────────────


def _profile(target: Any) -> Any:
    from iaiops.core.runtime.sensor import binding

    profile = binding.endpoint_profile(target)
    if profile is None:
        raise DescriptionUnusableError(
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
        # The description has no such channel: configuration, not the instrument.
        raise DescriptionUnusableError(str(exc.args[0])) from exc


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


def port_held_error(path: str) -> Exception:
    """The error for a port another program holds — not a network or device fault."""
    from iaiops.core.runtime.session_factory import OTLinkHeldError

    return OTLinkHeldError(
        f"Serial port {path} is in use by another program — not taken from it "
        "(the plant's own software may depend on it).",
        protocol="serial",
    )


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
                raise port_held_error(path) from exc
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
        try:
            if self._port is not None:
                return bytes(self._port.read(4096))
            data = self._sock.recv(4096) if self._sock else b""
        except TimeoutError:
            return b""
        except OSError as exc:  # includes pyserial's SerialException on unplug
            raise OTConnectionError(f"Serial link lost: {exc}", protocol="serial") from exc
        if data == b"" and self._sock is not None:
            raise OTConnectionError(
                "The serial device server closed the connection.", protocol="serial"
            )
        return data

    def flush_input(self) -> None:
        """Discard everything already received (a reply to an earlier query, or
        lines that waited in a buffer) — bounded, for an idle poll device."""
        if self._port is not None:
            self._port.reset_input_buffer()
        deadline = time.monotonic() + FLUSH_LIMIT_S
        while time.monotonic() < deadline and self.read():
            pass

    def write(self, data: bytes) -> None:
        try:
            if self._port is not None:
                self._port.write(data)
            elif self._sock is not None:
                self._sock.sendall(data)
        except OSError as exc:
            raise OTConnectionError(f"Serial link lost: {exc}", protocol="serial") from exc

    def close(self) -> None:
        for closer in (self._port, self._sock):
            if closer is not None:
                try:
                    closer.close()
                except OSError:
                    pass
        self._port = self._sock = None


# ── one-shot read ────────────────────────────────────────────────────────────


def _framer(profile: Any, synced: bool = True) -> LineFramer:
    f = profile.framing
    return LineFramer(
        terminator=f.terminator, encoding=f.encoding, max_line=f.max_line, synced=synced
    )


def _decode(channel: Any, line: str | None, reason: str) -> Any:
    if line is None:
        raise InvalidReadingError(f"{channel.name}: {reason}")
    return decode_line(channel, line)


def _first_line(link: Any, framer: LineFramer, window: float) -> tuple[str | None, str] | None:
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        lines = framer.feed(link.read())
        if lines:
            return lines[0]
    return None


def read_value(target: Any, ref: str) -> float | int:
    """Read one point once, from a line framed AFTER this read started.

    Listen: the first complete line after opening (the partial line the open landed
    in is dropped) within ``stale_after_s``. Poll: input flushed, the profile's query
    sent once, the first line after it within ``timeout_s``. Silence is a
    ``SerialSilenceError`` — the device did not answer.
    """
    channel = channel_for(target, ref)
    profile = _profile(target)
    _check_terms(target, profile)
    listen = profile.mode == "listen"
    window = float(target.stale_after_s) if listen else float(getattr(target, "timeout_s", 5) or 5)
    link = SerialLink(target).open()
    try:
        if listen:
            line = _first_line(link, _framer(profile, synced=False), window)
        else:
            link.flush_input()
            link.write(profile.query.encode("ascii"))
            line = _first_line(link, _framer(profile), window)
    finally:
        link.close()
    if line is None:
        raise SerialSilenceError(
            f"Serial {ref}: opened the link but heard nothing for {window:g} s — check the "
            "cable, port, baud rate / framing, or whether the instrument is sending.",
            protocol="serial",
        )
    return _decode(channel, *line).value


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
        synced=False,  # the partial line the open landed in is not shown
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
    """One held link for a collection run.

    Listen: a reader thread drains the link continuously and stamps each line with
    the moment it ARRIVED, so a read never takes a line that waited in a buffer as
    fresh, and a burst never leaves the newest line unread. Poll: no thread — each
    read flushes, sends the query, and takes the answer that came after it.
    """

    def __init__(self, target: Any) -> None:
        self.target = target
        self.profile = _profile(target)
        _check_terms(target, self.profile)
        self.link = SerialLink(target)
        self.lock = threading.Lock()
        self.latest: tuple[str | None, str] | None = None
        self.latest_at = 0.0
        self.opened_at = 0.0
        self.error: Exception | None = None
        self.running = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.link.open()
        self.opened_at = time.monotonic()
        if self.profile.mode == "listen":
            self.running = True
            self.thread = threading.Thread(target=self._pump, daemon=True)
            self.thread.start()

    def _pump(self) -> None:
        framer = _framer(self.profile, synced=False)
        while self.running:
            try:
                lines = framer.feed(self.link.read())
            except Exception as exc:  # noqa: BLE001 — surfaced to the next read
                with self.lock:
                    self.error = exc
                return
            if lines:
                with self.lock:
                    self.latest, self.latest_at = lines[-1], time.monotonic()

    def stop(self) -> None:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        self.link.close()


@contextmanager
def serial_session(target: Any):
    session = SerialSession(target)
    session.start()
    try:
        yield session
    finally:
        session.stop()


def _check_unchanged(session: SerialSession) -> None:
    """A profile edited mid-run would decode with the old pattern under the new
    unit: reopen instead (the runner reconnects on a connection error)."""
    if _profile(session.target) is not session.profile:
        raise OTConnectionError(
            "The serial profile changed during the run — reopening with the new one.",
            protocol="serial",
        )


def _listen_line(session: SerialSession, ref: str) -> tuple[str | None, str]:
    stale = float(session.target.stale_after_s)
    deadline = session.opened_at + stale
    while True:
        with session.lock:
            error, latest, latest_at = session.error, session.latest, session.latest_at
        if error is not None:
            raise OTConnectionError(f"Serial link lost: {error}", protocol="serial")
        if latest is not None or time.monotonic() >= deadline:
            break
        time.sleep(0.02)  # first line since the link opened: same window as any line
    if latest is None:
        raise OTNoReadingError(
            f"Serial {ref}: no line within {stale:g} s since the link opened.",
            protocol="serial",
        )
    age = time.monotonic() - latest_at
    if age > stale:
        raise OTNoReadingError(
            f"Serial {ref}: no line for {age:.1f} s — stale (stale_after_s {stale:g}).",
            protocol="serial",
        )
    return latest


def _poll_line(session: SerialSession, ref: str) -> tuple[str | None, str]:
    if session.latest is not None and time.monotonic() - session.latest_at <= POLL_REUSE_S:
        return session.latest  # same tick, another channel: one query, not one per channel
    session.link.flush_input()
    session.link.write(session.profile.query.encode("ascii"))
    line = _first_line(
        session.link,
        _framer(session.profile),
        float(getattr(session.target, "timeout_s", 5) or 5),
    )
    if line is None:
        raise OTNoReadingError(f"Serial {ref}: no answer to the query.", protocol="serial")
    session.latest, session.latest_at = line, time.monotonic()
    return line


def session_read(session: SerialSession, ref: str) -> tuple[Any, str]:
    """Collection read on a held link. Stale or undecodable → no reading (a gap)."""
    channel = channel_for(session.target, ref)
    _check_unchanged(session)
    if session.profile.mode == "listen":
        line = _listen_line(session, ref)
    else:
        line = _poll_line(session, ref)
    try:
        return _decode(channel, *line).value, ""
    except InvalidReadingError as exc:
        raise OTNoReadingError(f"Serial {ref}: {exc}", protocol="serial") from exc


__all__ = [
    "SerialLink",
    "SerialSession",
    "SerialSilenceError",
    "channel_for",
    "read_value",
    "serial_session",
    "session_read",
    "sniff",
]
