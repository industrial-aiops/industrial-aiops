"""Which profile decodes which endpoint (HLD §16.5 S3).

A Modbus endpoint is one device, so it carries one ``sensor_profile``. An IO-Link
master carries a device per port, so it carries ``port_profiles`` — a port →
profile map. Paths are resolved next to ``config.yaml`` and every profile is
loaded when the config is: a broken profile fails once, at load, naming its
endpoint.

The target keeps resolved *paths*, not profile objects, so a ``TargetConfig``
stays a plain description; :func:`cached_profile` turns a path into a profile and
re-reads the file only when it changes.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from iaiops.core.runtime.sensor.profile import SensorProfile, load_profile_file

#: IO-Link masters in the field have 4–16 ports; the connector sweeps up to 32.
MAX_PORT = 32

_CACHE: dict[str, tuple[int, SensorProfile]] = {}
_LOCK = threading.Lock()


def cached_profile(path: str) -> SensorProfile:
    """Load a profile, reusing the parsed copy until the file's mtime changes."""
    stamp = Path(path).stat().st_mtime_ns
    with _LOCK:
        hit = _CACHE.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    profile = load_profile_file(path)
    with _LOCK:
        _CACHE[path] = (stamp, profile)
    return profile


def parse_port_profiles(raw: Any, endpoint: str) -> tuple[tuple[int, str], ...]:
    """``{2: tof.yaml}`` → ``((2, "tof.yaml"),)``; ports validated, order fixed."""
    if raw in (None, "", {}):
        return ()
    if not isinstance(raw, dict):
        raise ValueError(f"Endpoint {endpoint!r}: port_profiles must map port → profile file.")
    out = []
    for key, value in raw.items():
        try:
            port = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Endpoint {endpoint!r}: port_profiles key {key!r} is not a port."
            ) from exc
        if not 1 <= port <= MAX_PORT:
            raise ValueError(
                f"Endpoint {endpoint!r}: port_profiles port {port} must be 1..{MAX_PORT}."
            )
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Endpoint {endpoint!r}: port {port} needs a profile file path.")
        out.append((port, value.strip()))
    return tuple(sorted(out))


def _resolve(path: str, base_dir: Path) -> str:
    candidate = Path(path).expanduser()
    return str(candidate if candidate.is_absolute() else (base_dir / candidate).resolve())


def _load_checked(path: str, endpoint: str, protocol: str) -> None:
    try:
        profile = load_profile_file(path)
    except FileNotFoundError as exc:
        raise ValueError(f"Endpoint {endpoint!r}: sensor profile {path} does not exist.") from exc
    except ValueError as exc:
        raise ValueError(f"Endpoint {endpoint!r}: sensor profile {path}: {exc}") from exc
    if profile.protocol != protocol:
        raise ValueError(
            f"Endpoint {endpoint!r} is {protocol}, but sensor profile {path} is a "
            f"{profile.protocol} profile."
        )


def bind_profiles(target: Any, base_dir: Path) -> Any:
    """Validate and resolve a target's profile paths; return a new target."""
    name, protocol = str(target.name), str(target.protocol)
    single = str(getattr(target, "sensor_profile", "") or "")
    ports = tuple(getattr(target, "port_profiles", ()) or ())
    if single and protocol != "modbus":
        raise ValueError(
            f"Endpoint {name!r}: sensor_profile is for a Modbus device"
            + (
                "; an IO-Link master has a device per port — use port_profiles."
                if protocol == "iolink"
                else "."
            )
        )
    if ports and protocol != "iolink":
        raise ValueError(f"Endpoint {name!r}: port_profiles is for an IO-Link master only.")
    if not single and not ports:
        return target
    resolved_single = _resolve(single, base_dir) if single else ""
    resolved_ports = tuple((port, _resolve(path, base_dir)) for port, path in ports)
    for path in ([resolved_single] if resolved_single else []) + [p for _, p in resolved_ports]:
        _load_checked(path, name, protocol)
    return replace(target, sensor_profile=resolved_single, port_profiles=resolved_ports)


def endpoint_profile(target: Any) -> SensorProfile | None:
    """The Modbus endpoint's profile, or ``None`` when it has none."""
    path = str(getattr(target, "sensor_profile", "") or "")
    return cached_profile(path) if path else None


def port_profile(target: Any, port: int) -> SensorProfile | None:
    """The profile bound to one IO-Link port, or ``None``."""
    for bound_port, path in getattr(target, "port_profiles", ()) or ():
        if int(bound_port) == int(port):
            return cached_profile(path)
    return None


__all__ = [
    "MAX_PORT",
    "bind_profiles",
    "cached_profile",
    "endpoint_profile",
    "parse_port_profiles",
    "port_profile",
]
