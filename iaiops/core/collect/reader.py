"""The cross-protocol read, as a public capability rather than a private helper.

The dispatch already existed — ``iaiops.core.brain.monitor._read_point`` reaches
the capability registry's ``monitor_read`` for each protocol. But it was private
and lived inside the change-of-value monitor, so a second consumer had to either
import a private name from the analysis layer or duplicate the dispatch.

This module is that dispatch, named and exported. ``brain.monitor`` keeps its own
helper (its contract is its own); what changes is that collection no longer
reaches into the analysis layer to read a device.

**Not every protocol has one**, and that is a fact about the protocols rather
than a gap to paper over: a Modbus holding register has no name, an OPC-UA node
does, and some connectors are stream- or file-shaped instead of point-shaped. A
protocol without the capability raises a teaching error — never a silent wrong
value.
"""

from __future__ import annotations

from typing import Any


def can_collect(protocol: str) -> bool:
    """True when ``protocol`` can be sampled point-by-point on a schedule."""
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

    cap = get_capabilities(str(protocol or ""))
    return bool(cap) and cap.monitor_read is not UNSUPPORTED


#: Protocols whose data is PUSHED to us. Their reader serves a last-value cache,
#: which is only honest when the endpoint states how often a point publishes.
PUSH_PROTOCOLS = frozenset({"mqtt"})


def _serial_reason(target: Any) -> str:
    if not getattr(target, "sensor_profile", ""):
        return "no `sensor_profile` — a serial line is not decoded without one"
    from iaiops.core.runtime.sensor.binding import endpoint_profile

    try:
        profile = endpoint_profile(target)
    except (OSError, ValueError) as exc:
        return f"sensor profile unreadable ({exc})"
    if profile.mode == "listen" and not float(getattr(target, "stale_after_s", 0) or 0) > 0:
        return "no `stale_after_s`, which a listening serial endpoint requires"
    return ""


def collectable_reason(target: Any) -> str:
    """Why this ENDPOINT cannot be sampled on a schedule — "" when it can.

    `can_collect` answers for the PROTOCOL. An endpoint needs more: the MQTT tap
    refuses to start without `stale_after_s`, so grading the site "continuous
    collection — ready" on the protocol alone promised something the very next
    command refused.
    """
    protocol = str(getattr(target, "protocol", "") or "")
    if not can_collect(protocol):
        return f"protocol {protocol!r} has no point-read path in this build"
    if protocol == "serial":
        return _serial_reason(target)
    if protocol == "iolink" and not getattr(target, "port_profiles", ()):
        return (
            "no `port_profiles` — IO-Link process data is not decoded without a sensor "
            "profile per port (`iaiops sensor import-iodd` drafts one)"
        )
    if protocol in PUSH_PROTOCOLS:
        try:
            interval = float(getattr(target, "stale_after_s", 0) or 0)
        except (TypeError, ValueError):
            interval = 0.0
        if interval <= 0:
            return "no `stale_after_s`, which collection requires on a push protocol"
    return ""


def ref_problems(target: Any, refs: tuple[str, ...] | list[str]) -> list[str]:
    """Refs this endpoint cannot even parse — checked BEFORE a run starts.

    Inside a run a malformed ref fails on every tick, and on a held session each
    failure also drops the connection: a typo becomes a week of gaps. Only
    protocols with a ref grammar are checked; the rest are not second-guessed.
    """
    protocol = str(getattr(target, "protocol", "") or "")
    if protocol == "modbus":
        from iaiops.connectors.modbus.points import check_ref
        from iaiops.core.runtime.sensor.binding import endpoint_profile

        def check(ref: str) -> None:
            check_ref(ref, endpoint_profile(target))

    elif protocol == "iolink":
        from iaiops.connectors.iolink.points import check_ref as check_iolink

        def check(ref: str) -> None:
            check_iolink(target, ref)

    elif protocol == "serial":
        from iaiops.connectors.serial.ops import channel_for

        def check(ref: str) -> None:
            channel = channel_for(target, ref)
            if not channel.unit:
                raise ValueError(
                    f"Serial channel {channel.name!r} takes its unit only from each line; "
                    "a series that mixes kg and g is not one series. Give it a fixed unit "
                    "(lines with another unit are then refused)."
                )

    else:
        return []
    problems = []
    for ref in refs:
        try:
            check(ref)
        except (ValueError, OSError) as exc:  # a bound profile deleted since load is a problem too
            problems.append(str(exc))
    return problems


def collectable_protocols() -> tuple[str, ...]:
    """Every protocol that continuous collection can currently drive."""
    from iaiops.core.runtime.capabilities import REGISTRY

    return tuple(sorted(p for p in REGISTRY if can_collect(p)))


def read_point(target: Any, ref: str) -> tuple[Any, str]:
    """Read one point → ``(value, source_timestamp)``. Raises on an unsupported protocol."""
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

    protocol = str(getattr(target, "protocol", ""))
    cap = get_capabilities(protocol)
    reader = cap.monitor_read if cap else UNSUPPORTED
    if reader is UNSUPPORTED:
        supported = ", ".join(collectable_protocols()) or "(none)"
        raise ValueError(
            f"Protocol {protocol!r} has no point-read path, so it cannot be sampled on a "
            f"schedule. Collectable today: {supported}."
        )
    return reader(target, ref)


def session_read_for(protocol: str):
    """The session-scoped read for ``protocol``, or ``None``.

    ``None`` is not a failure — it means this protocol reconnects per read, which
    is what every protocol did before and what one-shot CLI reads still want.
    Collection simply does not get to hold a connection for it.
    """
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

    cap = get_capabilities(str(protocol or ""))
    if not cap or cap.session_read is UNSUPPORTED:
        return None
    return cap.session_read


def session_builder_for(protocol: str):
    """The session opener for ``protocol``, or ``None`` when it has none."""
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

    cap = get_capabilities(str(protocol or ""))
    if not cap or cap.session_builder is UNSUPPORTED:
        return None
    return cap.session_builder


__all__ = [
    "read_point",
    "ref_problems",
    "can_collect",
    "collectable_protocols",
    "session_read_for",
    "session_builder_for",
]
