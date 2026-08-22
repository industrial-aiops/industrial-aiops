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


__all__ = ["read_point", "can_collect", "collectable_protocols"]
