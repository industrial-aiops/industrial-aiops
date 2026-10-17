"""Read one sensor point once and say how far it got (HLD §16.2 / §17.2).

The engine behind ``sensor_read_channel`` (MCP) and ``iaiops sensor read`` (CLI)
— one engine, two front-ends (HLD §3.1). The answer keeps the three levels apart
and never reports a lower one as a higher one (D41):

* ``reachable`` — did the device answer? ``None`` when nothing was contacted.
* ``decodable`` — did the answer decode into a measurement? ``None`` when the
  device never answered: a timeout says nothing about decoding.
* value + unit + accuracy band + the profile's verification level, only when both
  are true.

A ref the endpoint cannot read (malformed, unknown channel, unprofiled port) is
refused before anything is contacted. Nothing is stored and no config is written.
"""

from __future__ import annotations

from typing import Any

#: Protocols whose points this probe judges (the rest have no profile layer).
SENSOR_PROTOCOLS = ("modbus", "iolink")


def _profile_context(target: Any, ref: str) -> dict[str, Any]:
    """Profile id / verification / band for a profile-channel ref; {} otherwise."""
    from iaiops.core.runtime.sensor.binding import endpoint_profile, port_profile

    protocol = str(getattr(target, "protocol", ""))
    if protocol == "modbus":
        from iaiops.connectors.modbus.points import is_channel_ref, profile_channel

        if not is_channel_ref(ref):
            return {}
        profile = endpoint_profile(target)
        channel = profile_channel(ref, profile)
    else:
        from iaiops.connectors.iolink.points import parse_ref

        port, name = parse_ref(ref)
        profile = port_profile(target, port)
        if profile is None:
            return {}
        channel = profile.channel(name)
    band = channel.accuracy.band if channel.accuracy is not None else None
    return {"profile": profile.id, "verified": profile.verified, "band": band}


def _untyped(target: Any, ref: str) -> bool:
    if str(getattr(target, "protocol", "")) != "modbus":
        return False
    from iaiops.connectors.modbus.points import is_channel_ref, parse_point

    return not is_channel_ref(ref) and parse_point(ref).legacy


def read_channel(target: Any, ref: str) -> dict[str, Any]:
    """Read ``ref`` once on ``target``; report reachable / decodable separately."""
    from iaiops.core.collect.reader import ref_problems
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities
    from iaiops.core.runtime.sensor.binding import unit_for

    name = str(getattr(target, "name", ""))
    protocol = str(getattr(target, "protocol", ""))
    base: dict[str, Any] = {"endpoint": name, "ref": ref, "contacted": False}
    if protocol not in SENSOR_PROTOCOLS:
        return {
            **base,
            "levels": {"reachable": None, "decodable": None},
            "reason": f"{protocol!r} has no sensor-profile layer; this reads "
            f"{' / '.join(SENSOR_PROTOCOLS)} points.",
        }
    problems = ref_problems(target, (ref,))
    if problems:
        return {**base, "levels": {"reachable": None, "decodable": False}, "reason": problems[0]}
    cap = get_capabilities(protocol)
    if not cap or cap.read_ref is UNSUPPORTED:
        return {
            **base,
            "levels": {"reachable": None, "decodable": None},
            "reason": f"No per-ref read for {protocol!r} in this build.",
        }
    try:
        answer = cap.read_ref(target, ref)
    except Exception as exc:  # noqa: BLE001 — the device not answering is the finding
        return {
            **base,
            "contacted": True,
            "levels": {"reachable": False, "decodable": None},
            "reason": f"{type(exc).__name__}: {exc}",
        }
    contacted = {**base, "contacted": True}
    if not answer.get("good", True):
        return {
            **contacted,
            "levels": {"reachable": True, "decodable": False},
            "value": None,
            "reason": str(answer.get("reason", "")),
        }
    return {
        **contacted,
        "levels": {"reachable": True, "decodable": True},
        "value": answer.get("value"),
        "unit": unit_for(target, ref),
        "band": None,
        "verified": None,
        "profile": None,
        **_profile_context(target, ref),
        "untyped": _untyped(target, ref),
    }


__all__ = ["SENSOR_PROTOCOLS", "read_channel"]
