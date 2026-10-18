"""Query the sensor profile library shipped in ``iaiops/sensor_profiles`` (HLD §17.3).

Read-only. An entry is listed with its id, category, protocol, verification level
and — for IO-Link — the device identity it was written for, so an operator can
find a candidate profile for a device they have read the identity of. A match is
a SUGGESTION (D52): one device id can run several process-data layouts, and
binding a profile to an endpoint stays a person's edit of config.yaml (D51).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from iaiops.core.runtime.sensor.profile import SensorProfile, load_profile_file

LIBRARY_DIR = Path(__file__).resolve().parents[3] / "sensor_profiles"


def _files() -> list[Path]:
    return sorted(LIBRARY_DIR.glob("*/*.yaml"))


def _entry(path: Path, profile: SensorProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "category": path.parent.name,
        "protocol": profile.protocol,
        "verified": profile.verified,
        "source": profile.source,
        "description": profile.description,
        "vendor_id": profile.vendor_id,
        "device_id": profile.device_id,
        "derived_from": profile.derived_from or None,
        "channels": [c.name for c in profile.channels],
        "path": str(path),
    }


def list_profiles(
    protocol: str | None = None,
    vendor_id: int | None = None,
    device_id: int | None = None,
) -> list[dict[str, Any]]:
    """Library entries, optionally filtered by protocol and IO-Link identity."""
    out = []
    for path in _files():
        profile = load_profile_file(path)
        if protocol and profile.protocol != protocol:
            continue
        if vendor_id is not None and profile.vendor_id != vendor_id:
            continue
        if device_id is not None and profile.device_id != device_id:
            continue
        out.append(_entry(path, profile))
    return out


def get(profile_id: str) -> tuple[Path, SensorProfile]:
    """The library entry with this id → (path, profile); KeyError names the known ids."""
    for path in _files():
        profile = load_profile_file(path)
        if profile.id == profile_id:
            return path, profile
    known = ", ".join(load_profile_file(p).id for p in _files())
    raise KeyError(f"No library profile {profile_id!r}. known: {known}")


__all__ = ["LIBRARY_DIR", "get", "list_profiles"]
