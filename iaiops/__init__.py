"""iaiops — Industrial-AIOps: governed, read-first OT/industrial data tap.

A preview AI-ops tool for *reading* (and, gated, writing) industrial control
systems across OPC-UA, Modbus-TCP, S7comm, Mitsubishi MC, MTConnect,
MQTT/Sparkplug B, EtherNet/IP, EtherCAT, and SECS/GEM — plus a cross-protocol
intelligence layer (dataflow / connection / subscription / tag / alarm
diagnostics and OEE/asset analytics). Every tool runs through the shared
governance harness (audit / budget / risk-tier / undo). Read-first: the few
write/command tools are off by default (dry-run) and MOC-gated at high risk_tier.
"""

__version__ = "0.4.0"
