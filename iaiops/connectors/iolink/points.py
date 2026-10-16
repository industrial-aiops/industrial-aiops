"""IO-Link points: ``port<N>/<channel>``, decoded only through a profile (HLD §16 S3).

The master hands back process data as raw octets whose layout is device-specific.
A port is decoded only when the endpoint binds a profile to it
(``port_profiles``); a port without one refuses rather than guess a layout
(D44) — a guessed layout yields a plausible wrong number, not an error.

**Identity.** If the profile names the device it was written for
(``match: {vendor_id, device_id}``), the device on the port is checked before
anything is decoded: a sensor swapped for a different model would otherwise be
decoded with the wrong layout. The check (one master session reading the
device-identity datapoints) is cached per master and port for
:data:`IDENTITY_TTL_S`, and forgotten as soon as a read on that port fails — a
swap goes through a disconnect, so it is usually re-checked at once and at worst
within the window. A master that will not report the identity is a refusal, not
a skipped check.

**Process-data length.** If the profile states ``pd_bits``, an image of another
length is refused: offsets count from the end of the image, so another active
process-data layout (same device id) would shift every field.

Not checked here: whether the master flags the process data as valid
(PD-valid / device status) — how masters report it is 待核实.

The vendorid/deviceid datapoints follow the ifm IoT-Core tree; other masters'
encodings are 待核实 (numbers and ``"0x…"``/decimal strings are accepted).
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from iaiops.core.runtime.sensor import Channel, SensorProfile, decode_bits
from iaiops.core.runtime.sensor.binding import MAX_PORT, port_profile
from iaiops.core.runtime.session_factory import OTNoReadingError

GRAMMAR = "port<N>/<channel>, e.g. port2/distance"
IDENTITY_TTL_S = 30.0

_REF = re.compile(r"^port(\d+)/(\S+)$")
_verified: dict[tuple[str, int, int, int], float] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def clear_identity_cache() -> None:
    with _lock:
        _verified.clear()


def parse_ref(ref: str) -> tuple[int, str]:
    """``"port2/distance"`` → ``(2, "distance")``; refuse anything else."""
    match = _REF.match(str(ref or "").strip())
    if not match:
        raise ValueError(f"IO-Link ref {ref!r} is not in the grammar {GRAMMAR}.")
    port = int(match.group(1))
    if not 1 <= port <= MAX_PORT:
        raise ValueError(f"IO-Link ref {ref!r}: port must be 1..{MAX_PORT}.")
    return port, match.group(2)


def port_channel(target: Any, ref: str) -> tuple[int, SensorProfile, Channel]:
    """Resolve a ref to (port, profile, channel), or refuse with what is missing."""
    port, name = parse_ref(ref)
    profile = port_profile(target, port)
    if profile is None:
        raise ValueError(
            f"IO-Link ref {ref!r}: port {port} has no sensor profile, so its process "
            "data is not decoded (a guessed layout gives a plausible wrong number). Add "
            f"it under port_profiles in config.yaml — `iaiops sensor import-iodd` drafts one."
        )
    try:
        return port, profile, profile.channel(name)
    except KeyError as exc:
        raise ValueError(str(exc.args[0])) from exc


def check_ref(target: Any, ref: str) -> None:
    """Raise ``ValueError`` if ``ref`` cannot be read on this endpoint — touches nothing."""
    port_channel(target, ref)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            return None
    return None


def _master(target: Any) -> str:
    """The master's resolved base URL — two masters configured by ``host:`` alone
    share an empty ``agent_url``, so that cannot be the key."""
    from iaiops.connectors.iolink.transport import _iolink_base_url

    return f"{getattr(target, 'name', '')}@{_iolink_base_url(target)}"


def _identity_key(target: Any, port: int, profile: SensorProfile) -> tuple[str, int, int, int]:
    return (_master(target), port, int(profile.vendor_id or 0), int(profile.device_id or 0))


def _forget(target: Any, port: int) -> None:
    master = _master(target)
    with _lock:
        for key in [k for k in _verified if k[0] == master and k[1] == port]:
            del _verified[key]


def verify_identity(target: Any, port: int, profile: SensorProfile) -> None:
    """Refuse (as a gap) when the device on ``port`` is not the profile's device."""
    if profile.vendor_id is None or profile.device_id is None:
        return
    key = _identity_key(target, port, profile)
    with _lock:
        checked_at = _verified.get(key)
    if checked_at is not None and _now() - checked_at < IDENTITY_TTL_S:
        return
    from iaiops.connectors.iolink import ops

    device = (ops.device_info(target, port) or {}).get("device") or {}
    vendor, device_id = _as_int(device.get("vendorid")), _as_int(device.get("deviceid"))
    if vendor is None or device_id is None:
        raise OTNoReadingError(
            f"IO-Link port {port}: the master did not report a readable device identity "
            f"({device.get('vendorid')!r}/{device.get('deviceid')!r}), so it cannot be checked "
            f"against profile {profile.id!r}. Not decoded.",
            protocol="iolink",
        )
    if (vendor, device_id) != (profile.vendor_id, profile.device_id):
        raise OTNoReadingError(
            f"IO-Link port {port} has vendor {vendor} device {device_id}; profile "
            f"{profile.id!r} is for vendor {profile.vendor_id} device {profile.device_id}. "
            "A different sensor is on this port — not decoded with the wrong layout.",
            protocol="iolink",
        )
    with _lock:
        _verified[key] = _now()


def read_value(target: Any, ref: str) -> float | int:
    """Read and decode one IO-Link point. ``InvalidReadingError`` = not a measurement."""
    from iaiops.connectors.iolink import ops

    port, profile, channel = port_channel(target, ref)
    verify_identity(target, port, profile)
    try:
        data = bytes(ops.read_pdin(target, port)["bytes"])
        return decode_bits(channel, data, expected_bits=profile.pd_bits).value
    except Exception:
        # A swap goes through a disconnect: never let a cached identity outlive
        # a failed read on that port.
        _forget(target, port)
        raise


__all__ = [
    "GRAMMAR",
    "IDENTITY_TTL_S",
    "check_ref",
    "clear_identity_cache",
    "parse_ref",
    "port_channel",
    "read_value",
    "verify_identity",
]
