"""iaiops — governed, read-only OT/industrial telemetry & problem surfacing.

A preview AI-ops tool for *reading* industrial control systems over OPC-UA and
Modbus-TCP and surfacing problems (alarms / threshold breaches / simple
statistical anomalies). Every MCP tool runs through a vendored governance
harness (audit / budget / risk-tier). Strictly non-destructive in this preview —
no writes to PLCs, controllers, or SCADA servers.
"""

__version__ = "0.3.0"
