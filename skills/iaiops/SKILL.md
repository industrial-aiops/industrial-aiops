---
name: iaiops
description: >-
  Vendor-neutral, governed industrial/OT data tap + intelligent troubleshooting.
  Read (and, gated, write) PLCs, controllers, machine tools and IIoT brokers over
  OPC-UA, Modbus-TCP, Siemens S7comm, Mitsubishi MC, MTConnect, MQTT/Sparkplug B,
  Allen-Bradley EtherNet/IP, EtherCAT (pysoem/SOEM), SECS/GEM (semiconductor /
  display fab equipment over HSMS), PROFINET (DCP discovery), the building edition
  (BACnet/IP), and Phoenix Contact PLCnext vPLC — plus cross-protocol diagnostics
  ("no-data" dataflow diagnosis, OPC-UA connection self-diagnosis, subscription
  health, ISA-18.2 alarm bad-actors, tag/historian health, and the AI downtime
  root-cause copilot) and analytics (OEE/downtime, asset inventory, OPC-UA HDA,
  change-of-value). Use when the task names any industrial protocol, a
  PLC/SCADA/HMI/historian/CNC/RTU/IED, a semiconductor/display fab or SECS/GEM
  equipment, an electrical substation, an opc.tcp:// or mqtt:// endpoint,
  OEE/downtime, downtime root-cause, or OT asset inventory. Routes to
  the iaiops MCP server. Read-first; writes are MOC-gated (high risk, dry-run +
  double-confirm). Do NOT use for IT/network gear, Kubernetes, hypervisors, or
  backups — those are separate AIops tools.
---

# iaiops — industrial data tap + intelligent troubleshooting

One governed MCP server exposing read-first tools across 12 industrial protocols plus a
cross-protocol intelligence layer. Narrow the exposed surface per site with
`IAIOPS_MCP` (e.g. `IAIOPS_MCP=fab` or `IAIOPS_MCP=opcua,modbus`), or just launch the matching pre-scoped
script (`iaiops-mcp-opcua`, `iaiops-mcp-fab`, … — sugar over `IAIOPS_MCP`). Every tool runs through the iaiops governance
harness (audit / budget / risk-tier / undo). **Read-first.** The 8 write tools are
gated as Management-of-Change: `risk=HIGH`, `dry_run=True` by default, CLI requires
a double-confirm, the before-value is captured for undo. **Never write to a
production control system without authorization.** Preview / mock-or-sim validated —
verify against live equipment. Start with `protocols_supported` to see what's
configured and `<protocol> doctor` to test a link.

## When to route here
Task mentions: OPC-UA / opc.tcp, Modbus, Siemens S7 / S7-1200/1500, Mitsubishi /
MELSEC, MTConnect / CNC machine monitoring, MQTT / Sparkplug B / Unified Namespace,
Allen-Bradley / ControlLogix / CompactLogix / EtherNet-IP, EtherCAT / CoE / SDO /
PDO / SOEM, SECS/GEM / SECS-II / HSMS / semiconductor / display fab / wafer / panel
/ MES equipment / SVID / ECID, PROFINET / DCP / name-of-station, HART / HART-IP /
process instrumentation / transmitter, BACnet / BACnet-IP / building automation / HVAC /
facility / 厂务 / Who-Is, OEE / downtime, OT asset inventory, "no data / stale
tag" diagnosis, **downtime root-cause / why did the line stop**, OPC-UA "won't
connect", subscription drops, alarm flood / ISA-18.2.

**Energy protocols route elsewhere:** IEC 60870-5-104 / IEC-104, DNP3 / outstation,
IEC 61850 / MMS / IED, substation, energy / power / utility SCADA → use the
**iaiops-energy** MCP server (`pip install iaiops-energy`, then `iaiops-energy-mcp`),
not this one.

## Tools by protocol

### OPC-UA (read-only) — opc.tcp endpoints
- `opcua_server_info` — status, build info, namespace array
- `opcua_browse` — browse node tree from a node id (bounded depth)
- `opcua_read_node` — value + datatype + source timestamp + status code
- `opcua_read_many` — batch read node ids (bounded)
- `opcua_subscribe_sample` — bounded sampling, then returns (never loops)
- `opcua_read_alarms` — best-effort active alarm/condition surfacing
- `opcua_read_history` — Historical Access (HDA): raw history over a [start,end] window
- `opcua_diagnose_connection` — classify *why* a connect fails (certificate / security
  policy / auth / firewall / dns / port / config) with the exact fix, not a raw error
- `opcua_discover_tags` — auto-discover OPC-UA tags and build a semantic asset model
- `health_summary` — classify node-ids vs warn/alarm thresholds
- `anomaly_scan` — sample a node, flag statistical outliers

### Modbus-TCP / Modbus-RTU (read-only here)
- `modbus_read_holding` (FC03), `modbus_read_input` (FC04), `modbus_read_coils`
  (FC01), `modbus_read_discrete` (FC02) — with decode hints
- `modbus_detect_byte_order` — auto-detect the word/byte order of a register block
- `modbus_list_templates` — built-in vendor register-map templates (name/type/tags)
- `modbus_apply_template` — read a register block, decode into named tags via a template
- `modbus_health_summary` — classify registers vs thresholds

### Siemens S7comm (pyS7; S7-300/400/1200/1500)
- `s7_cpu_info` — CPU identity + run/stop
- `s7_read_area` — read N items of a type from an S7 memory area
- `s7_read_db` — read N items from a data block
- `s7_read_many` — batch raw pyS7 address strings
- `s7_write_db` — **[WRITE][HIGH][MOC]** write one value to a DB (off by default)

### Mitsubishi MC (pymcprotocol 3E; Q/L/iQ)
- `mc_cpu_status` — MELSEC CPU type/code
- `mc_read_words` / `mc_read_bits` — batch word/bit devices from a head device
- `mc_read_many` — random-read scattered word + dword in one request
- `mc_write_words` — **[WRITE][HIGH][MOC]** write words (off by default)

### MTConnect (read-only; all CNC machine tools)
- `mtconnect_probe` — device model (devices → components → data items)
- `mtconnect_current` — latest value of every data item (machine snapshot)
- `mtconnect_sample` — bounded stream of recent observations
- `mtconnect_assets` — cutting tools / fixtures / programs
- `mtconnect_oee_snapshot` — availability / execution / mode / program (OEE inputs)

### MQTT / Sparkplug B / UNS (paho-mqtt; full Tahu protobuf decode)
- `mqtt_read_topic` — plain MQTT bounded message collect
- `sparkplug_decode_payload` — decode one raw Sparkplug B payload to metrics
- `sparkplug_subscribe_sample` — bounded sample w/ full decode + birth/death/seq
- `sparkplug_node_list` — edge nodes/devices + online state + primary-host STATE
- `uns_browse` — browse the live topic tree (UNS) under a filter (bounded)
- `uns_live_audit` — capture the LIVE UNS topic tree (bounded), then audit it
- `sparkplug_live_schema` — capture a LIVE Sparkplug schema (bounded) → drift-ready dict
- `uns_live_drift` — capture the LIVE Sparkplug schema (bounded) and diff vs baseline
- `mqtt_publish` — **[WRITE][HIGH][MOC]** publish/command to a topic (off by default)

### Allen-Bradley EtherNet/IP (pycomm3; ControlLogix/CompactLogix)
- `eip_controller_info` — controller identity (proves the CIP link)
- `eip_list_tags` — discover controller tag list (names/types/structures)
- `eip_read_tag` — read one tag (or array element) with its type
- `eip_read_many` — batch read (auto multi-packet)
- `eip_write_tag` — **[WRITE][HIGH][MOC]** write one tag value (off by default)

### EtherCAT (pysoem/SOEM; **Linux + root/CAP_NET_RAW + dedicated NIC + real slaves**)
Optional extra `pip install iaiops[ethercat]`; **no software simulator** (hardware-only,
macOS unsupported). Tools degrade to a teaching error if pysoem/permission/NIC/bus is missing.
- `ethercat_master_state` — master/working-counter state + expected vs found slave count
- `ethercat_slaves` — bus scan: enumerate slaves (id/vendor/product/rev/addr/AL-state)
- `ethercat_slave_info` — one slave: SM/FMMU config + object-dictionary summary
- `ethercat_read_sdo` — CoE SDO upload (acyclic mailbox read of an OD entry)
- `ethercat_read_pdo` — one cyclic snapshot of a slave's input process-data image
- `ethercat_write_sdo` — **[WRITE][HIGH][MOC]** CoE SDO download (off by default)
- `ethercat_set_state` — **[WRITE][HIGH][MOC]** AL-state transition (can START/STOP motion; off by default)

### SECS/GEM (read-only; semiconductor / display fab equipment ↔ host over HSMS)
Optional extra `pip install iaiops[secsgem]` (or the `iaiops[fab]` bundle). We are the
HOST (HSMS ACTIVE). SECS/GEM (SEMI E5 SECS-II · E30 GEM · E37 HSMS) is the fab equipment
↔ MES standard — the entry ticket for panel/semiconductor fabs.
- `secsgem_equipment_status` — establish the GEM link + Are-You-There (S1F1/F2)
- `secsgem_list_status_variables` — SVID namelist (S1F11/F12)
- `secsgem_read_status_variables` — SVID values (S1F3/F4)
- `secsgem_list_equipment_constants` — ECID namelist (S2F29/F30)
- `secsgem_read_equipment_constants` — ECID values (S2F13/F14)
- `secsgem_list_alarms` — alarm list (S5F5/F6): ALID, ALCD, text
- `secsgem_list_process_programs` — PPID directory (S7F19/F20)

> **Fab routing (semiconductor / display, e.g. panel TFT-LCD/OLED).** A fab equipment
> is two layers: its **internal control** (PLC over S7 / OPC-UA / Modbus) and its
> **MES-facing** SECS/GEM (HSMS) interface — different jobs, don't conflate. Use
> `IAIOPS_MCP=fab` (secsgem + opcua + s7 + modbus). Read-first: `secsgem_equipment_status`
> to confirm the link, then SVID/ECID/alarms; the PLC layer via the S7/OPC-UA tools.

### PROFINET (DCP discovery + one gated DCP Set; pnio-dcp, layer-2 raw socket)
Optional extra `pip install iaiops[profinet]` (or the `iaiops[factory]` bundle). Needs
raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the PROFINET subnet; `host` is
THIS machine's IP on that subnet. Read-first discovery + identify — no RT cyclic data.
The one write, `profinet_dcp_set`, is MOC-gated like every other write.
- `profinet_discover` — DCP IdentifyAll: every station on the segment (name/MAC/IP/role)
- `profinet_identify_station` — identify one station by its name-of-station
- `profinet_station_params` — targeted DCP Get by MAC (name + IP suite)
- `profinet_asset_inventory` — register with IO-controller vs IO-device role decoding
- `profinet_dcp_set` — **[WRITE][HIGH][MOC]** DCP Set: re-address one station
  (name-of-station / IP). `dry_run=True` by default + approver double-confirm;
  re-addressing a live station can break its IO-controller relation

### HART-IP (read-only; process instrumentation — transmitters, valve positioners)
Part of the `process` profile (`IAIOPS_MCP=process` = opcua + modbus + hart).
`transport` is `udp` (default) or `tcp` on port 5094.
- `hart_device_identity` — universal device identity (command 0) via HART-IP
- `hart_primary_variable` — primary variable (command 1): value + unit code
- `hart_dynamic_variables` — dynamic variables + loop current (command 3)
- `hart_burst_sample` — sample the periodically-published (burst) HART variables

### Energy edition (变电/电力) — ships separately
The substation/utility telecontrol edition (IEC 60870-5-104 / DNP3 / IEC 61850 MMS)
moved to its own package: `pip install iaiops-energy` then `iaiops-energy-mcp`
(github.com/industrial-aiops/industrial-aiops-energy). It reuses this package's core +
brain; monitor-direction only, preview/待核实 against live RTUs/IEDs.

### Building edition (read-first; facility / HVAC / 厂务 — BACnet/IP)
Optional bundle `pip install iaiops[building]` and `IAIOPS_MCP=building`. `host` is THIS
machine's BACnet/IP interface (`ip` or `ip/mask`). Read-first; the one write,
`bacnet_write_property`, is MOC-gated like every other write.
- `bacnet_discover` — Who-Is: devices on the local BACnet/IP network
- `bacnet_object_list` — a device's object/point list
- `bacnet_read_property` — one object property (default presentValue)
- `bacnet_read_points` — presentValue of all analog/binary/multistate points (HVAC snapshot)
- `bacnet_cov_subscribe` — bounded Change-of-Value capture for one BACnet object
- `bacnet_read_trend_log` — read buffered records from a device's TrendLog object
- `bacnet_write_property` — **[WRITE][HIGH][MOC]** write ONE object property
  (off by default: `dry_run=True` + approver double-confirm; can command
  building equipment — setpoints, outputs)

## Cross-protocol intelligence

### Diagnostics — `skills` umbrella: troubleshooting
- `diagnose_dataflow` — localize a "no data" break across an endpoint's reachable hops
- `downtime_root_cause` — **AI downtime root-cause copilot (flagship)**: correlate alarms /
  tags / dataflow / machine-state around an incident window into an evidence-cited,
  **advisory** verdict (read-only; cites only real signals; `insufficient_evidence` over
  guessing). `downtime_root_cause_live` gathers the evidence itself from an endpoint.
- `learn_cause_weights` — learn a per-site RCA {cause: weight} profile from history
- `historian_health` — bad-tag / flatline / gap detection over a series
- `alarm_bad_actors` — ISA-18.2 alarm-flood analysis (rate vs <6/12/30, Pareto
  offenders, chattering, standing) over an event list
- `tag_health` — rank tag offenders by bad-quality / flatline / range / anomaly
- `subscription_health` — sequenced-feed loss/reorder/overload (OPC-UA monitored items
  or Sparkplug B): sequence gaps, republish-rejection rate, overloaded channels
- `data_quality_scorecard` — fleet data-TRUST rollup: scores each tag 0-100 on staleness /
  dead heartbeat / bad-quality / flatline / gaps / anomaly, per endpoint + fleet
- `data_quality_fleet_rollup` — cross-endpoint fleet rollup of data-TRUST: worst tags +
  bad quality across the fleet
- `heartbeat_health` — first-class heartbeat/watchdog liveness (flatline = dead upstream)
- `uns_topic_audit` — UNS naming conformance + topic-sprawl governance (casing collisions,
  scattered leaves, depth outliers, duplicates → clean/minor/sprawling)
- `uns_schema_drift` — Sparkplug schema drift baseline-vs-current → none/additive/breaking

### Analytics
- `oee_compute` — OEE = Availability × Performance × Quality
- `downtime_events` — detect running→stopped transitions, categorize stoppages
- `oee_multidim` — aggregate OEE across machine × part × shift
- `asset_inventory` — actively fingerprint endpoints (vendor/model/firmware/protocol)
  into an asset register (active discovery, **not** passive SPAN/tap)
- `monitor_changes` — capture only the value CHANGES of a point over a bounded window

### Unified asset model / alias governance
- `cross_protocol_asset_model` — fuse per-protocol tag feeds into ONE unified asset model
- `adopt_alias_map` — adopt + persist the canonical alias map for a site (baseline)
- `diff_alias_map` — diff a fresh discovery run against the adopted baseline

### 信创 / China entry + compliance
- `compliance_mapping` — 《工控系统网络安全防护指南》 ↔ iaiops governance self-assessment
  (分区隔离 / 可审计 / 双向认证 / 最小权限 / 数据保护 / 自主可控) with honest status + gaps
- `compliance_frameworks` — 跨框架对照: 防护指南 ↔ 等保 2.0 (GB/T 22239) ↔ IEC 62443
- `compliance_dengbao_levels` — 等保 2.0 二级 vs 三级 per-pillar deltas + honest posture
- `historian_push` — write collected telemetry to a domestic TSDB (TDengine / IoTDB)
  or the local queryable SQLite store (sink="sqlite" → ~/.iaiops/data.db);
- `compliance_report` — render the crosswalk into a deliverable 等保/62443 Markdown report
  (per-pillar L2/L3 status, FR1–6 crosswalk, honest gap list; onboarding aid, 非认证)
- `compliance_evidence_bundle` — export the audit-evidence zip (audit rows JSONL + hash-chain
  verification + rules.yaml + doctor summary) for an auditor
- `historian_push` — write collected telemetry to a domestic TSDB (TDengine / IoTDB);
  data egress to the operator's own historian, not a control write. See docs/CHINA.md
  for air-gapped install + 国产 OS/芯/PLC validation matrix (待核实).

### Queryability / export (get the data OUT)
- `export_data` — export samples from the LOCAL SQLite sink (data.db) to CSV /
  SQLite / Parquet for Excel / Power BI / SQL (bounded ≤200-row inline preview;
  parquet needs `pip install 'iaiops[export]'`). CLI: `iaiops export`; Grafana:
  `iaiops metrics serve` (Prometheus /metrics, see docs/GRAFANA.md).

### Meta / roadmap
- `protocols_supported` — capability map (protocols, status, tools, connection params)
- Roadmap: EtherCAT EoE/FoE/SoE mailbox protocols; EtherNet/IP PLC-5 / SLC (PCCC),
  Micro800; passive asset discovery; OPC-UA certificate security.

## Setup
`iaiops init` (interactive wizard, per-protocol prompts) writes
`~/.iaiops/config.yaml`; credentials go to the encrypted store
(`~/.iaiops/secrets.enc`, master password via `IAIOPS_MASTER_PASSWORD`). Run
`iaiops doctor` to probe each configured endpoint. Full per-protocol reference,
connection params, simulator-test guide, and MCP JSON examples are in the README.

## Safety
Read-first. The 8 write tools (`s7_write_db`, `mc_write_words`, `mqtt_publish`,
`eip_write_tag`, `ethercat_write_sdo`, `ethercat_set_state`, `profinet_dcp_set`,
`bacnet_write_property`) default to `dry_run=True`, require a CLI double-confirm
(approver), and record an undo descriptor from the captured before-value/state.
EtherCAT state changes can START or STOP machine motion; a PROFINET DCP Set can
re-address a live station; a BACnet write can command building equipment. Do not
point this at production control systems without authorization. No tool returns secrets.
