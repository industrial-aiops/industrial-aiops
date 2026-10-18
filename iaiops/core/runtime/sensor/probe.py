"""Read one sensor point once and say how far it got (HLD §16.2 / §17.2).

The engine behind ``sensor_read_channel`` (MCP) and ``iaiops sensor read`` (CLI)
— one engine, two front-ends (HLD §3.1). The answer keeps the three levels apart
and never reports a lower one as a higher one (D41):

* ``reachable`` — did the device answer? A device that answers with an ERROR
  (a Modbus exception for a wrong address, an IO-Link master reporting another
  device on the port) answered: reachable. ``None`` when nothing was contacted.
* ``decodable`` — did the answer decode into a measurement? ``None`` when the
  device never answered or nothing was contacted: neither says anything about
  decoding.
* value + unit + accuracy band + the profile's verification level, only when both
  are true.

A ref the endpoint cannot read (malformed, unknown channel, unprofiled port) is
refused before anything is contacted: both levels ``None``, ``refused: true``.
Nothing is stored and no config is written.
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


def _switch_meaning(target: Any, ref: str) -> dict[str, Any]:
    """For a switching ref: the active level and what the 1/0 means (HLD §17.5b)."""
    if str(getattr(target, "protocol", "")) != "modbus":
        return {}
    from iaiops.connectors.modbus.points import SWITCH_TABLES, is_channel_ref, parse_point
    from iaiops.connectors.modbus.points import profile_channel as channel_for
    from iaiops.core.runtime.sensor import SwitchLayout
    from iaiops.core.runtime.sensor.binding import endpoint_profile

    try:
        if is_channel_ref(ref):
            layout = channel_for(ref, endpoint_profile(target)).layout
            active = layout.active if isinstance(layout, SwitchLayout) else ""
        else:
            point = parse_point(ref)
            active = point.active if point.table in SWITCH_TABLES else ""
    except Exception:  # noqa: BLE001 — metadata only
        return {}
    if not active:
        return {}
    wire = "1" if active == "high" else "0"
    return {
        "active": active,
        "meaning": f"1 = actuated, 0 = not (active-{active}: a {wire} on the wire is actuated)",
    }


def read_channel(target: Any, ref: str) -> dict[str, Any]:
    """Read ``ref`` once on ``target``; report reachable / decodable separately."""
    from iaiops.core.collect.reader import ref_problems
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities
    from iaiops.core.runtime.sensor.binding import unit_for
    from iaiops.core.runtime.session_factory import OTNoReadingError, OTProtocolError

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
        return {
            **base,
            "refused": True,
            "levels": {"reachable": None, "decodable": None},
            "reason": problems[0],
        }
    cap = get_capabilities(protocol)
    if not cap or cap.read_ref is UNSUPPORTED:
        return {
            **base,
            "levels": {"reachable": None, "decodable": None},
            "reason": f"No per-ref read for {protocol!r} in this build.",
        }
    try:
        answer = cap.read_ref(target, ref)
    except (OTProtocolError, OTNoReadingError) as exc:
        # The device ANSWERED — with an error, or with something that is not a
        # measurement. Reporting it offline sends someone to check the cable when
        # the register address (or the sensor on the port) is what is wrong.
        return {
            **base,
            "contacted": True,
            "levels": {"reachable": True, "decodable": False},
            "reason": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:  # noqa: BLE001 — the device not answering is the finding
        return {
            **base,
            "contacted": True,
            "levels": {"reachable": False, "decodable": None},
            "reason": f"{type(exc).__name__}: {exc}",
        }
    contacted = {**base, "contacted": True}
    if not answer.get("good", True) or answer.get("value") is None:
        return {
            **contacted,
            "levels": {"reachable": True, "decodable": False},
            "value": None,
            "reason": str(answer.get("reason") or "the device answered with no value"),
        }
    try:
        context = _profile_context(target, ref)
        note = ""
    except Exception as exc:  # noqa: BLE001 — a good reading must not be lost to metadata
        context, note = {}, f"profile details unavailable after the read: {exc}"
    result = {
        **contacted,
        "levels": {"reachable": True, "decodable": True},
        "value": answer.get("value"),
        "unit": unit_for(target, ref),
        "band": None,
        "verified": None,
        "profile": None,
        **context,
        "untyped": _untyped(target, ref),
        **_switch_meaning(target, ref),
    }
    return {**result, "note": note} if note else result


__all__ = ["SENSOR_PROTOCOLS", "read_channel"]
