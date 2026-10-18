"""Can each configured point be DECODED? (HLD §16.2 — the middle level of three.)

Readiness already says whether an endpoint can be reached and collected. This
adds the level in between for the protocols whose points need decoding:

* a typed Modbus point or a profile channel decodes;
* a bare Modbus address is *untyped* — collected as an unsigned 16-bit word,
  which is right for many registers and silently wrong for every 32-bit, float
  or signed one; the config cannot say which;
* a ref the endpoint cannot read at all (malformed, or a channel with no
  profile) is listed with the reason — collection refuses it before starting.

Profiles still marked 待核实 are named even when everything decodes: decoding
"as the datasheet says" is not decoding "as this device does".

Contacts nothing: config and profile files only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from iaiops.core.readiness.model import Requirement

_JUDGED = ("modbus", "iolink")


def _bound_profiles(target: Any) -> list[Any]:
    from iaiops.core.runtime.sensor.binding import endpoint_profile, port_profile

    profiles = []
    single = endpoint_profile(target) if getattr(target, "sensor_profile", "") else None
    if single is not None:
        profiles.append(single)
    for port, _path in getattr(target, "port_profiles", ()) or ():
        profiles.append(port_profile(target, port))
    return profiles


def _is_profile_ref(protocol: str, ref: str) -> bool:
    """A ref that decodes through a profile channel, so it should have a unit."""
    from iaiops.connectors.modbus.points import is_channel_ref

    return protocol == "iolink" or (protocol == "modbus" and is_channel_ref(ref))


def sensor_point_facts(targets: tuple[Any, ...]) -> dict[str, Any]:
    """Per-point decode status across the endpoints whose points need decoding."""
    from iaiops.connectors.modbus.points import is_channel_ref, parse_point
    from iaiops.core.collect.reader import ref_problems
    from iaiops.core.runtime.sensor.binding import unit_for

    judged = 0
    decoded = 0
    untyped: list[str] = []
    unreadable: list[str] = []
    unverified: set[str] = set()
    no_unit: list[str] = []
    for target in targets:
        protocol = str(getattr(target, "protocol", ""))
        if protocol not in _JUDGED:
            continue
        judged += 1
        name = str(getattr(target, "name", ""))
        try:
            unverified.update(p.id for p in _bound_profiles(target) if p.verified == "待核实")
        except (OSError, ValueError) as exc:
            unreadable.append(f"{name}: sensor profile unreadable ({exc})")
            continue
        for tag in getattr(target, "tags", ()) or ():
            ref = str(tag.get("ref", "") if isinstance(tag, Mapping) else getattr(tag, "ref", ""))
            problems = ref_problems(target, (ref,))
            if problems:
                unreadable.append(f"{name}:{ref} — {problems[0]}")
            elif protocol == "modbus" and not is_channel_ref(ref) and parse_point(ref).legacy:
                untyped.append(f"{name}:{ref}")
            else:
                decoded += 1
                if _is_profile_ref(protocol, ref) and not unit_for(target, ref):
                    no_unit.append(f"{name}:{ref}")
    return {
        "judged_endpoints": judged,
        "decoded": decoded,
        "untyped": untyped,
        "unreadable": unreadable,
        "unverified_profiles": sorted(unverified),
        "no_unit": no_unit,
    }


def decodable_points_req(facts: dict[str, Any]) -> Requirement:
    """Optional: collection runs either way, but untyped values are not understood."""
    points = facts.get("sensor_points") or {}
    untyped = list(points.get("untyped") or ())
    unreadable = list(points.get("unreadable") or ())
    unverified = list(points.get("unverified_profiles") or ())
    no_unit = list(points.get("no_unit") or ())
    if not points.get("judged_endpoints"):
        return Requirement(
            key="decodable_points",
            label="every Modbus / IO-Link point can be decoded",
            met=True,
            detail="not applicable — no Modbus or IO-Link endpoint is configured",
            optional=True,
        )
    parts = [f"{points.get('decoded', 0)} point(s) decode"]
    if untyped:
        parts.append(f"{len(untyped)} untyped (read as uint16): {', '.join(untyped[:5])}")
    if unreadable:
        parts.append(f"{len(unreadable)} cannot be read: {'; '.join(unreadable[:3])}")
    if unverified:
        parts.append(f"decoded by profiles still 待核实: {', '.join(unverified[:5])}")
    if no_unit:
        parts.append(
            f"{len(no_unit)} stored without a unit (profile unit still 待核实): "
            f"{', '.join(no_unit[:5])}"
        )
    return Requirement(
        key="decodable_points",
        label="every Modbus / IO-Link point can be decoded",
        met=not untyped and not unreadable,
        detail="; ".join(parts),
        fix=(
            "Give each Modbus point its type — `ir:<addr>:float32:<order>`, "
            "`hr:<addr>:int16*0.1` — or bind a sensor profile and use `ch:<name>`. "
            "IO-Link ports need a profile under port_profiles (`iaiops sensor import-iodd`). "
            "A unit still marked 待核实 (an IODD unit code) is stored empty until the profile "
            "says the real unit."
        ),
        optional=True,
    )


#: Roles that COUNT production. A switching point may hold none of them (D61).
_COUNT_ROLES = ("total_count", "good_count", "reject_count")


def _is_switching(target: Any, ref: str) -> bool:
    """A Modbus `di:` / `co:` point, or a profile channel on a switching bit."""
    if str(getattr(target, "protocol", "")) != "modbus":
        return False
    from iaiops.connectors.modbus.points import SWITCH_TABLES, is_channel_ref, parse_point
    from iaiops.connectors.modbus.points import profile_channel as channel_for
    from iaiops.core.runtime.sensor import SwitchLayout
    from iaiops.core.runtime.sensor.binding import endpoint_profile

    try:
        if is_channel_ref(ref):
            return isinstance(channel_for(ref, endpoint_profile(target)).layout, SwitchLayout)
        return parse_point(ref).table in SWITCH_TABLES
    except (OSError, ValueError):
        return False  # an unreadable ref is reported by decodable_points, not here


def switching_count_tags(targets: tuple[Any, ...]) -> list[str]:
    """Tags declared as a production counter that sit on a switching sensor."""
    found = []
    for target in targets:
        for tag in getattr(target, "tags", ()) or ():
            ref = str(tag.get("ref", "") if isinstance(tag, Mapping) else getattr(tag, "ref", ""))
            role = str(
                tag.get("role", "") if isinstance(tag, Mapping) else getattr(tag, "role", "")
            )
            if role in _COUNT_ROLES and _is_switching(target, ref):
                found.append(f"{getattr(target, 'name', '')}:{ref} ({role})")
    return found


def count_source_req(facts: dict[str, Any]) -> Requirement:
    """D61: a switching point is not a production counter.

    Polling an on/off switch misses every pulse shorter than the interval, so a
    count built from it is systematically low — and plausibly so. The count must
    come from a counter (a DI module's or a PLC's counter register).
    """
    found = list(facts.get("switching_count_tags") or ())
    return Requirement(
        key="count_source",
        label="production counts come from a counter, not a polled switch",
        met=not found,
        detail=(
            f"counted from a switching sensor: {', '.join(found[:5])}"
            if found
            else "no production-count role sits on a switching sensor"
        ),
        fix=(
            "Map the count role to a counter register — the DI module's or the PLC's "
            "pulse counter (e.g. hr:<addr>:uint32:<order>). Polled on/off misses every "
            "pulse shorter than the sampling interval."
        ),
    )


__all__ = [
    "count_source_req",
    "decodable_points_req",
    "sensor_point_facts",
    "switching_count_tags",
]
