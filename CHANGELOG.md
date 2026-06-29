# Changelog

## 0.4.0 — Industrial-AIOps

First release under the standalone **`industrial-aiops`** org (split out of the
`AIops-tools` IT line). Same governance harness, read-first stance, and preview /
mock-or-sim validation caveat — now a monorepo with a shared core, per-protocol
connectors, a menu-configurable MCP, and a semiconductor/display fab connector.

### Breaking
- **Renamed `ot-aiops` → `iaiops`**: package `ot_aiops`→`iaiops`, CLI/MCP
  `ot-aiops`→`iaiops`, env `OT_AIOPS_*`→`IAIOPS_*`, home `~/.ot-aiops`→`~/.iaiops`.
  Legacy env vars and the legacy home directory are honored as a fallback so
  existing installs keep unlocking secrets / reading audit.
- **Protocol client libraries are now optional extras** — the base package installs
  and imports without them; install only what a site runs:
  `pip install "iaiops[opcua,modbus]"` (or `iaiops[all]`). A call to a
  not-installed protocol returns a teaching error pointing at the right extra.

### Added
- **Shared core** — `iaiops/core/{governance,runtime,brain}`; connectors import it.
- **`IAIOPS_MCP` menu** — expose only the protocols a site runs (named profiles
  `all` / `fab` / `factory` / `process`, or a comma list). `fab` profile = 29 tools
  vs 66 for `all`.
- **SECS/GEM connector** — host-side reads for semiconductor/display fab equipment
  over HSMS (SEMI E5/E30/E37) via the `secsgem` extra: equipment status, SVID/ECID
  namelists + values, alarms, process programs (7 tools).
- **OPC-UA connection self-diagnosis** (`opcua_diagnose_connection`) — classifies a
  failed connect (certificate / security policy / auth / firewall / dns / port /
  config) with the fix; wired into `iaiops doctor`.
- **`subscription_health`** — sequenced-feed loss/reorder/overload (OPC-UA monitored
  items or Sparkplug B): sequence gaps, republish-rejection rate, overloaded channels.
- **Per-industry edition bundles** — `iaiops[fab]` / `iaiops[factory]` / `iaiops[process]`.

### Notes
- 66 tools across 9 protocols. Still **preview** — validated against simulators /
  mocks, not live equipment.
