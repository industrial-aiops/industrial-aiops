# Changelog

## 0.7.0 — HART-IP, tag discovery, data-quality & Modbus depth (2026-06-30)

New read-only **HART-IP** process-instrumentation connector, **OPC-UA tag
auto-discovery + semantic modeling**, data-quality watchdog enhancements,
Modbus byte-order auto-detect / vendor templates / RTU serial, and per-protocol
named MCP entry points — plus a live binding-validation pass that fixed three
real defects mocks never caught (see the 0.6.0 validation notes below). All
read-first; previews carry honest `待核实` caveats.

### Added — packaging / DX
- **Per-protocol & per-edition named MCP entry points** — convenience console
  scripts `iaiops-mcp-opcua`, `iaiops-mcp-modbus`, … (one per protocol) plus
  `iaiops-mcp-fab` / `-factory` / `-process` / `-energy` / `-building` (named
  profiles). Each is a thin shim (`mcp_server/entrypoints.py`) that injects the
  equivalent `IAIOPS_MCP=<name>` selection then starts the **same** server via
  `server.main` — no server logic duplicated. The shim set is generated
  data-driven from `PROTOCOL_MODULES` + `NAMED_PROFILES`, so it can't drift from
  the menu, and produces an identical registered tool set to `IAIOPS_MCP=<name>`.
  Pure sugar — the `IAIOPS_MCP` env var already delivered the capability.

### Added — Modbus connector
- **Modbus byte-order auto-detect + vendor register templates** (R4 community pain) —
  `modbus_detect_byte_order` (PURE decode logic, no device): decodes a raw register
  block under every candidate word/byte order for a numeric type (uint16/int16/
  uint32/int32/float32 → AB/BA and ABCD/DCBA/BADC/CDAB) and scores them against a
  known `hint` value and/or a plausible `[value_min, value_max]` band, returning the
  best order + confidence. Plus `modbus_list_templates` / `modbus_apply_template`: a
  curated set of vendor register maps (generic big-endian / word-swapped float blocks,
  Eastron SDM630 energy meter, Schneider PM5xxx power meter) that decode a block into
  named engineering tags. New modules `iaiops/connectors/modbus/byteorder.py` +
  `templates.py`. Fully unit-tested.
- **Modbus-RTU (serial) transport** — the Modbus connector now speaks Modbus-RTU over
  a serial line as well as Modbus-TCP. Endpoints set `transport: rtu` (or just a
  `serial_port:`) with `baudrate` / `parity` / `stopbits` / `bytesize`; the connection
  layer builds pymodbus's `ModbusSerialClient` and the same read ops (holding / input /
  coils / discrete) work unchanged. Client construction + config plumbing are
  unit-verified (monkeypatched pymodbus client). **待核实:** the live-serial round-trip
  needs real RS-485/USB hardware and is not CI-verifiable.

### Added — verticals & protocols
- **HART-IP connector (read-only, process edition)** — `hart_device_identity` /
  `hart_primary_variable` / `hart_dynamic_variables` MCP tools + `iaiops hart` CLI
  (`iaiops/connectors/hart/`), over HART-IP (UDP 5094) via the `hart` extra
  (`hart-protocol`); added to the `process` profile/bundle. The HART command codec
  (build/parse) is **verified offline** against the real library; the **HART-IP wire
  transport is 待核实** (not validated against a live HART-IP server/gateway). Write
  and device-specific commands are intentionally NOT exposed (OT-dangerous on live
  instrumentation).

### Added — intelligence layer
- **Data-quality watchdog enhancements** (`iaiops/core/brain/dataquality.py`) — extends
  the data-trust scorecard with: (1) **configurable staleness/gap per tag and per feed**
  (`staleness_s` / `gap_threshold_s`, with a feed-level `staleness_s` default) so a slow
  daily counter is not judged like a 1Hz sensor, plus `flatline_after_s` to flag a stuck
  value by its longest stall; (2) **flatline / dead-heartbeat as a first-class scored
  `liveness` section** in the scorecard output (no longer buried in per-tag flags),
  reusing `_longest_stall`; (3) **cross-endpoint fleet rollup** — new
  `data_quality_fleet_rollup` brain fn + MCP tool + `iaiops diag dataquality-fleet` CLI
  that ranks endpoints by their single worst tag and aggregates bad-quality tag counts
  across every endpoint (extends the per-endpoint `_rollup_endpoint`). Pure analysis.
- **OPC-UA tag auto-discovery + semantic modeling** — `opcua_discover_tags` MCP tool
  + `iaiops opcua discover` CLI (`iaiops/connectors/opcua/discovery.py`): walks the
  address space, collects every Variable node enriched with datatype / value /
  engineering-unit, infers a heuristic semantic class (temperature / pressure / flow /
  setpoint / alarm / state / …), groups tags into assets by browse path, and proposes
  a clean canonical alias per tag with a naming-quality report (alias collisions /
  cryptic names). Advisory + read-only — no server-side rename. Skips OPC-UA ns=0
  infrastructure by default. Verified against a real in-process asyncua server.

## 0.6.0 — New verticals & protocols (PROFINET, energy, building, 信创) + intelligence

Breadth release: new field protocols and per-industry editions, China-market entry
artifacts, and two new read-only intelligence layers. Same read-first stance and
preview / mock-or-sim caveat. (Also includes a code-review hardening pass — see below.)

### Added — intelligence layer
- **Data-quality watchdog** — `data_quality_scorecard` (fleet data-TRUST rollup:
  scores each tag 0-100 on staleness / **dead heartbeat** / bad-quality / flatline /
  gaps / anomaly, rolled up per endpoint + fleet with ranked worst offenders) and
  `heartbeat_health` (first-class watchdog-liveness check). Pure analysis; also feeds
  the downtime root-cause copilot. CLIs `iaiops diag dataquality` / `iaiops diag heartbeat`.
- **UNS governance** — `uns_topic_audit` (UNS naming conformance + topic-sprawl:
  casing collisions, scattered leaves, depth outliers, duplicates → clean/minor/
  sprawling) and `uns_schema_drift` (Sparkplug NBIRTH baseline-vs-current →
  none/additive/breaking). CLIs `iaiops mqtt uns-audit` / `iaiops mqtt uns-drift`.

### Fixed (code-review hardening)
- **`iec61850` extra had a fabricated version pin** (`>=1.5` — uninstallable; PyPI tops
  out at 0.12.x) that broke `iaiops[energy]` resolution → corrected to `>=0.10,<1`.
- **`secsgem` was missing from `SUPPORTED_PROTOCOLS`** since v0.4.0 — config rejected
  every secsgem endpoint, making that connector unreachable → fixed + fully wired into
  the capability map.
- **RCA copilot crashed on mixed naive/aware timestamps** (operator's naive `start` vs a
  device's `...Z` alarm) → timestamp parsing now coerces naive→UTC everywhere.
- **PROFINET / BACnet / IEC-104 raised raw tracebacks** on the most common real failure
  (raw-socket permission / UDP bind) because the client was built outside the session
  `try` → builds moved inside; failures now translate to teaching errors.
- **SQL-injection hole** in the TDengine sink (unescaped timestamp; identifiers) → fixed.
  Plus: DNP3 integrity-poll harvested the wrong handler; IoTDB wrote local-tz/epoch-0;
  chattering alarms inflated RCA confidence; live sink errors escaped the error contract.
  15 regression tests added for the previously-untested paths.

### Fixed (binding validation pass, 2026-06-30)
Ran the preview/待核实 bindings against **real libraries + containerized servers**
(not mocks) — which surfaced three real bugs the mock suite could never catch:
- **`iec61850` extra pointed at the wrong PyPI distribution.** The prior pin
  `iec61850>=0.10,<1` resolves to an unrelated async-OOP client that exposes **none**
  of the `IedConnection_*` SWIG symbols the driver calls (0/14). Re-pinned to
  **`pyiec61850`** (the real libiec61850 SWIG binding, linux-only wheel); all 14
  driver symbols verified present, and the driver/connection imports now use it.
- **BACnet called a fabricated `whois()`** — BAC0 exposes `who_is()`; the mock fake
  duck-typed the wrong name, so it would have `AttributeError`'d against real gear.
- **TDengine `CREATE STABLE` used `value` as a column name** — a TDengine reserved
  word the live parser rejects with a syntax error → back-quoted in DDL.
- **Verified live:** IEC-104 (real c104 loopback link via `iec104_session`), IoTDB &
  TDengine (write→read round-trip via the real sinks). **Still 待核实:** DNP3
  (`pydnp3` has no wheel + needs a live outstation) and live-RTU/IED reads.
- **New guards:** `tests/test_binding_contracts.py` (per-binding library-API contract
  tests, `importorskip`-gated — run when an extra is installed) and
  `tests/test_protocol_consistency.py` (cross-registry meta-test that would have caught
  the historical `secsgem`-missing-from-`SUPPORTED_PROTOCOLS` regression).

### Added — verticals & protocols
- **PROFINET connector (read-only)** — layer-2 **PROFINET-DCP** discovery/identify
  via the optional `pnio-dcp` extra (`pip install iaiops[profinet]`):
  `profinet_discover` (DCP IdentifyAll — one broadcast surfaces every station on the
  segment), `profinet_identify_station` (by name-of-station), `profinet_station_params`
  (targeted DCP Get by MAC), and `profinet_asset_inventory` (register with
  IO-controller/IO-device role decoding). **Discovery + identify only** — no RT cyclic
  process data, and the disruptive DCP *Set* services (set-name/ip/blink/reset) are not
  exposed. Needs raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the PROFINET
  subnet; added to the `factory` profile + bundle. Mock-tested, not yet hardware-verified.
- **Energy edition** — three read-only substation/utility telecontrol connectors,
  an `energy` MCP profile (`IAIOPS_MCP=energy`), and the `iaiops[energy]` bundle:
  - **IEC 60870-5-104** (`iaiops[iec104]`, `c104`): `iec104_connection_info`,
    `iec104_interrogate` (general interrogation), `iec104_read_point`.
  - **DNP3** (`iaiops[dnp3]`, `pydnp3`/opendnp3): `dnp3_link_status`,
    `dnp3_integrity_poll` (Class 0/1/2/3 database grouped by measurement type).
  - **IEC 61850 MMS** (`iaiops[iec61850]`, libiec61850): `iec61850_device_directory`,
    `iec61850_browse`, `iec61850_read` (object-reference + functional constraint).
  - **Monitor direction only** — control commands (C_SC/C_DC, CROB, Oper/SBO) and
    IEC-61850 GOOSE/SV are not exposed. **⚠️ Preview / 待核实**: library bindings are
    unverified against live RTUs/IEDs and kept out of `iaiops[all]` (iec61850 needs
    libiec61850 built; pydnp3 builds a native ext). Largest validation debt in the line.
- **Building edition** — **BACnet/IP** (ASHRAE 135) read-only facility/HVAC monitoring
  via the `iaiops[bacnet]` extra (BAC0/bacpypes3), the `building` MCP profile
  (`IAIOPS_MCP=building`), and the `iaiops[building]` bundle: `bacnet_discover`
  (Who-Is), `bacnet_object_list`, `bacnet_read_property`, `bacnet_read_points`
  (present-value snapshot of analog/binary/multistate points). Read-only — present-value
  writes are not exposed. **⚠️ Preview / 待核实**: BAC0 binding unverified against live gear.
- **信创 / China entry** — `compliance_mapping` (《工控系统网络安全防护指南》 ↔ iaiops
  governance self-assessment with honest per-control status), a national-TSDB
  historian sink `historian_push` (write collected telemetry to **TDengine**
  `iaiops[tdengine]` or **Apache IoTDB** `iaiops[iotdb]` — data egress to the
  operator's own historian, not a control write), CLIs `iaiops compliance` /
  `iaiops historian push`, and **docs/CHINA.md** (air-gapped wheelhouse install,
  国产 OS/芯/PLC validation matrix, compliance reference). **⚠️ 待核实**: 国产
  OS/芯/PLC and the TSDB write paths are documented but not hardware-verified.

### Notes
- 90 tools across 14 protocols (incl. 2 信创/compliance + 4 new intelligence tools).
  Still **preview** — mock/sim validated; the energy, building, and 信创 paths are
  unverified against live equipment (see docs/CHINA.md for the validation backlog).

## 0.5.0 — AI downtime root-cause copilot

The flagship cross-protocol intelligence step: orchestrate the existing read
tools + brain into an **evidence-cited, advisory** root-cause verdict for a
downtime/incident window. Read-first, mock/sim preview — unchanged stance.

### Added
- **`downtime_root_cause`** (brain `iaiops/core/brain/rca.py`, MCP tool, and
  `iaiops diag rca`) — correlates whatever evidence a site supplies (alarm events,
  tag samples, a `diagnose_dataflow` verdict, a machine-state series) around an
  incident window and ranks candidate causes. Highlights:
  - **Temporal correlation** — a cause precedes its effect, so signals *before*
    onset (within a configurable `lead_window_s`) outweigh signals *during* it;
    signals *after* onset are treated as consequences.
  - **Confidence by noisy-OR** (`1 − Π(1−wᵢ)`) — independent, agreeing evidence
    compounds toward (never reaching) certainty; a lone weak signal stays weak.
  - **Anti-hallucination** — every citation references a real supplied signal;
    thin evidence downgrades to `insufficient_evidence` with a concrete
    `recommended_next_data` list instead of a confident guess.
  - **Advisory / read-only** — proposes a human-approved, MOC-gated, undoable
    next step per cause; executes nothing.
- **`downtime_root_cause_live`** (brain `iaiops/core/brain/rca_collect.py`, MCP
  tool, and `iaiops diag rca-live`) — the copilot that **gathers its own evidence**:
  give it an endpoint + window + refs and it pulls a cross-protocol
  `diagnose_dataflow` probe, a short sampled series per ref (feeding `tag_health`),
  and active OPC-UA conditions, then runs the same advisory analysis. The gathered
  bundle is echoed under `collected_evidence`; reuses only existing read paths, adds
  light read load, and degrades (never raises) on a partial outage.

### Notes
- 68 tools across 9 protocols (7 cross-protocol diagnostics). Still **preview** —
  validated against simulators / mocks, not live equipment.

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
