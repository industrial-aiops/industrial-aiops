"""Stream egress — publish iaiops' OWN normalized reads + findings onto a message bus.

The third leg of the adapter belt (``ingress`` = protocol tap · ``core`` = normalize/govern/RCA ·
``egress`` = sinks + stream publishers + exporters). A *publisher* pushes normalized tag points,
alarm/RCA events, etc. onto a bus (NATS, …) so surrounding systems can subscribe — the site's bus is
kept EXTERNAL; iaiops never becomes a broker.

Read-first safe: egress carries only data/findings iaiops already *read* or *computed*; it is NOT a
control write. Adapters lazy-import their client, so the base package imports without any of them.
"""

from iaiops.core.egress.base import EgressError, get_publisher, points_to_messages

__all__ = ["EgressError", "get_publisher", "points_to_messages"]
