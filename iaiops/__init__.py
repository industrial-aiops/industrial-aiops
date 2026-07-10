"""iaiops — Industrial-AIOps: governed, read-first OT/industrial data tap.

A preview AI-ops tool for *reading* (and, gated, writing) industrial control
systems across OPC-UA, Modbus-TCP, S7comm, Mitsubishi MC, MTConnect,
MQTT/Sparkplug B, EtherNet/IP, EtherCAT, and SECS/GEM — plus a cross-protocol
intelligence layer (dataflow / connection / subscription / tag / alarm
diagnostics and OEE/asset analytics). Every tool runs through the shared
governance harness (audit / budget / risk-tier / undo). Read-first: the few
write/command tools are off by default (dry-run) and MOC-gated at high risk_tier.
"""

# Derive the version from the installed package metadata (pyproject is the single source of
# truth) so it never drifts on a version bump — see tests/test_smoke.py::test_version.
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("iaiops")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
