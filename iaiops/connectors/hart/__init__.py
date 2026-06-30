"""HART-IP connector (read-only process-instrumentation monitoring).

HART (Highway Addressable Remote Transducer) is the dominant smart field-device
protocol for process instrumentation (transmitters, valve positioners). HART-IP
tunnels native HART commands over UDP/TCP (port 5094) to a HART-IP server / gateway.

This connector is **read-only monitoring**: it reads universal HART variables
(primary variable, dynamic variables, device identity). It does NOT issue device-
specific or write/configure commands (OT-dangerous on live instrumentation).

Layering + honesty:
- The HART command CODEC (building command frames + parsing device responses) uses
  the ``hart-protocol`` library and is **verified offline** (a crafted long-frame
  ACK round-trips through the parser) — see ``codec.py`` + tests.
- The HART-IP **wire transport** (session-initiate + token-passing PDU over UDP)
  is implemented from the public spec and is **待核实** — not verified against a
  live HART-IP server/gateway here. It is isolated in ``transport.py``.
"""
