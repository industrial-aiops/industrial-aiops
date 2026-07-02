<!-- mcp-name: io.github.industrial-aiops/iaiops -->

# Industrial-AIOps

**English** · [中文](README.zh-CN.md)

**Governed, vendor-neutral industrial data tap + intelligent troubleshooting for AI agents — read-first tools across 12 field protocols: OPC-UA (incl. Historical Access + tag auto-discovery), Modbus-TCP/RTU (byte-order auto-detect + vendor templates), S7comm, Mitsubishi MC, MTConnect, MQTT/Sparkplug B (full decode), EtherNet/IP (Rockwell/Allen-Bradley Logix), EtherCAT (pysoem/SOEM), PROFINET (DCP), SECS/GEM (HSMS fab), HART-IP (process instrumentation), the building (BACnet/IP) edition, and Phoenix Contact PLCnext vPLC — plus an AI downtime root-cause copilot, data-quality watchdog, UNS governance, OEE/downtime, asset-inventory, and 信创 (TDengine/IoTDB historian sinks + 防护指南/等保2.0/IEC 62443 compliance mapping). The energy edition (变电/电力: IEC-104 / DNP3 / IEC-61850) now ships separately as [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy).**

Industrial-AIOps is the OT member of the [industrial-aiops](https://github.com/industrial-aiops) org. It is a **factory-level, vendor-neutral, governed data tap** that lets an AI agent safely *read* industrial control systems across many field protocols, plus a **cross-protocol intelligence layer** that localizes "no data" breaks, analyzes alarm floods (ISA-18.2), scores data trustworthiness, ranks unhealthy tags, computes OEE / categorizes downtime, builds an active asset register, auto-discovers OPC-UA tags into a semantic asset model, and — the flagship — runs an **AI downtime root-cause copilot** that correlates the evidence into an **evidence-cited, advisory** verdict. Read-first by design; the few write/command paths are OT-dangerous and gated by MOC discipline. Every tool runs through a vendored governance harness (audit / budget / risk-tier / undo).

> **v0.7.0 — validation status (honest).** Pure analysis + the OPC-UA path are tested against a **real in-process asyncua server**. The 信创 bindings were run against **real libraries + containers** in a 2026-06-30 validation pass: **IoTDB** + **TDengine** (live container write→read round-trip) are **verified**; the HART command codec is verified vs `hart-protocol`. **Phoenix Contact PLCnext vPLC** (virtualized PLC) is **route-verified** over its OPC-UA server (an in-process `asyncua` server reproducing the `Arp.Plc.Eclr` GDS address space) and a Modbus-TCP process-data block (`tests/test_plcnext_route.py`); live PLCnext hardware reads stay `待核实`. **Modbus-RTU (live serial)** is now **verified** (2026-07-02): the read ops round-trip over a real serial link built from a `socat` PTY pair + a `pymodbus` RTU server (`tests/test_modbus_rtu_live.py`), exercising the actual RTU framing — though not yet validated against a specific physical RS-485 device. The **BACnet/IP read path** is now **verified** (2026-07-02): a genuine Who-Is discover + present-value read round-trip against a **real bacpypes3 virtual BACnet/IP device** on a two-IP subnet in a Linux container (`tests/test_bacnet_live.py`), through the actual async BAC0 (2024+) stack — bridged onto a dedicated event loop so the sync connector works against the coroutine API. Live BACnet COV/trend-log reads and property writes on real HVAC gear stay `待核实`. **Still `待核实` (preview, not hardware-verified):** BACnet write/COV/trend on live HVAC, HART-IP wire transport (live gateway), EtherCAT (no software simulator — Linux + root + a real bus only). Mocked clients cover S7/MC/EtherNet-IP/SECS-GEM; MTConnect uses static XML fixtures; Sparkplug uses synthetic protobuf payloads. (The energy edition's IEC-104 / DNP3 / IEC-61850 validation lives in the [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) repo.) See *Safety*.

## Why

OT is exactly where you want an agent on a tight leash: read first, never blind-write. Industrial-AIOps is the **safe, neutral read wedge** — one package, one MCP server, many protocols — with governance and an intelligence layer that turns raw reads into actionable diagnoses.

---

## Consolidated capability matrix

| Protocol | Tool | Operation | R/W | risk_tier | Returns (key fields) |
|----------|------|-----------|:---:|:---------:|----------------------|
| OPC-UA | `opcua_server_info` | server status | R | low | state, product_name, namespaces |
| OPC-UA | `opcua_browse` | browse node tree | R | low | [{node_id, browse_name, depth}] |
| OPC-UA | `opcua_read_node` | read one node | R | low | value, datatype, source_timestamp, good |
| OPC-UA | `opcua_read_many` | batch read | R | low | [{node_id, value, ...}] |
| OPC-UA | `opcua_subscribe_sample` | bounded sample | R | low | {collected, samples[]} |
| OPC-UA | `opcua_read_alarms` | alarm surfacing | R | low | {active_alarms[], active_count} |
| OPC-UA | `opcua_read_history` | Historical Access (HDA) | R | low | {supported, count, values[]} |
| OPC-UA | `health_summary` | threshold classify | R | low | {overall, counts, offenders[]} |
| OPC-UA | `anomaly_scan` | stddev outliers | R | low | {mean, stddev, outliers[]} |
| Modbus | `modbus_read_holding` | FC03 | R | low | {raw_registers, decoded[]} |
| Modbus | `modbus_read_input` | FC04 | R | low | {raw_registers, decoded[]} |
| Modbus | `modbus_read_coils` | FC01 | R | low | {bits[]} |
| Modbus | `modbus_read_discrete` | FC02 | R | low | {bits[]} |
| Modbus | `modbus_health_summary` | threshold classify | R | low | {overall, counts, offenders[]} |
| S7comm | `s7_cpu_info` | CPU id + run/stop | R | low | {cpu_status, cpu_info} |
| S7comm | `s7_read_area` | read DB/M/I/Q | R | low | {items:[{address, value}]} |
| S7comm | `s7_read_db` | read data block | R | low | {items:[{address, value}]} |
| S7comm | `s7_read_many` | batch addresses | R | low | {items:[{address, value}]} |
| S7comm | `s7_write_db` | write data block | **W** | **high/MOC** | {before, written, _undo_id} |
| Mitsubishi MC | `mc_cpu_status` | CPU type | R | low | {cpu_type, cpu_code} |
| Mitsubishi MC | `mc_read_words` | word devices | R | low | {words[]} |
| Mitsubishi MC | `mc_read_bits` | bit devices | R | low | {bits[]} |
| Mitsubishi MC | `mc_read_many` | random read | R | low | {words[], dwords[]} |
| Mitsubishi MC | `mc_write_words` | write words | **W** | **high/MOC** | {before, written, _undo_id} |
| MTConnect | `mtconnect_probe` | device model | R | low | {devices:[{components:[{data_items}]}]} |
| MTConnect | `mtconnect_current` | latest values | R | low | {observations[]} |
| MTConnect | `mtconnect_sample` | bounded stream | R | low | {observations[]} |
| MTConnect | `mtconnect_assets` | assets | R | low | {assets[]} |
| MTConnect | `mtconnect_oee_snapshot` | OEE inputs | R | low | {availability, execution, verdict} |
| MQTT/Sparkplug | `mqtt_read_topic` | bounded read | R | low | {messages:[{topic, payload}]} |
| MQTT/Sparkplug | `sparkplug_subscribe_sample` | bounded SpB sample (full decode) | R | low | {samples:[{sparkplug, payload:{metrics[]}}], seq_gap_count} |
| MQTT/Sparkplug | `sparkplug_decode_payload` | decode raw SpB payload | R | low | {metrics:[{name, alias, datatype, value, is_historical}]} |
| MQTT/Sparkplug | `sparkplug_node_list` | node discovery + state | R | low | {nodes:[{group_id, edge_node_id, online, devices}], primary_hosts[]} |
| MQTT/Sparkplug | `uns_browse` | topic-tree browse | R | low | {topics[], tree{}} |
| MQTT/Sparkplug | `uns_topic_audit` | UNS naming + sprawl governance | R | low | {verdict, sprawl_findings, findings{casing_collisions[], scattered_leaves[], …}} |
| MQTT/Sparkplug | `uns_schema_drift` | Sparkplug schema-drift (baseline vs current) | R | low | {verdict (none/additive/breaking), node_changes[]} |
| MQTT/Sparkplug | `mqtt_publish` | publish/command | **W** | **high/MOC** | {published_bytes, applied} |
| EtherNet/IP | `eip_controller_info` | Logix controller id | R | low | {controller:{vendor, product_name, revision, serial}} |
| EtherNet/IP | `eip_list_tags` | tag discovery | R | low | {tag_count, tags:[{name, data_type, structure}]} |
| EtherNet/IP | `eip_read_tag` | read one tag/array | R | low | {tag, value, type, good} |
| EtherNet/IP | `eip_read_many` | batch read | R | low | {items:[{tag, value, type}]} |
| EtherNet/IP | `eip_write_tag` | write tag | **W** | **high/MOC** | {before, written, _undo_id} |
| Diagnostics | `diagnose_dataflow` | localize no-data | R | low | {verdict, diagnosis, hops[]} |
| Diagnostics | `alarm_bad_actors` | ISA-18.2 flood | R | low | {flood_verdict, top_offenders[]} |
| Diagnostics | `tag_health` | offender ranking | R | low | {overall, offenders[]} |
| Diagnostics | `historian_health` | gap/flatline | R | low | {verdict, gaps[]} |
| Diagnostics | `subscription_health` | sequenced-feed loss/reorder/overload | R | low | {verdict, missed_count, overloaded_channels[]} |
| Diagnostics | `downtime_root_cause` | AI downtime RCA copilot (cited, advisory) | R | low | {verdict, primary_cause, hypotheses:[{cause, confidence, evidence[]}]} |
| Diagnostics | `downtime_root_cause_live` | RCA copilot that gathers its own live evidence | R | low | {…downtime_root_cause…, collected_evidence} |
| Diagnostics | `data_quality_scorecard` | fleet data-trust rollup | R | low | {fleet_score, fleet_status, issue_breakdown, worst_tags[], endpoints[]} |
| Diagnostics | `heartbeat_health` | heartbeat/watchdog liveness | R | low | {alive, distinct_transitions, longest_stall_s, reason} |
| Analytics | `oee_compute` | OEE = A×P×Q | R | low | {availability, performance, quality, oee, oee_pct} |
| Analytics | `downtime_events` | stoppage detect + categorize | R | low | {event_count, total_downtime_s, by_category, events[]} |
| Analytics | `oee_multidim` | OEE machine×part×shift | R | low | {matrix[], worst_performers[], mean_oee} |
| Analytics | `asset_inventory` | active fingerprint | R | low | {assets:[{protocol, vendor, model, firmware, reachable}]} |
| Analytics | `monitor_changes` | bounded change-of-value | R | low | {change_count, changes:[{value, previous, wall_clock}]} |
| EtherCAT | `ethercat_master_state` | master/WKC + slave count | R | low | {master_state, expected_working_counter, slaves_found, slaves_expected} |
| EtherCAT | `ethercat_slaves` | bus scan | R | low | {slave_count, slaves:[{index, name, vendor_id, product_code, state}]} |
| EtherCAT | `ethercat_slave_info` | slave detail | R | low | {sync_managers[], fmmus[], object_dictionary[], input_bytes} |
| EtherCAT | `ethercat_read_sdo` | CoE SDO upload | R | low | {index, byte_length, hex, as_uint} |
| EtherCAT | `ethercat_read_pdo` | input PDO snapshot | R | low | {working_counter, input_hex, input_byte_length} |
| EtherCAT | `ethercat_write_sdo` | CoE SDO download | **W** | **high/MOC** | {before, written, applied} |
| EtherCAT | `ethercat_set_state` | AL-state transition | **W** | **high/MOC** | {before, requested, reached, applied} |
| PROFINET | `profinet_discover` | DCP IdentifyAll (segment-wide) | R | low | {station_count, stations:[{name_of_station, mac, ip, vendor_id, device_roles[]}]} |
| PROFINET | `profinet_identify_station` | identify by name-of-station | R | low | {found, name_of_station, mac, ip, device_family} |
| PROFINET | `profinet_station_params` | targeted DCP Get (by MAC) | R | low | {found, name_of_station, ip, netmask, gateway} |
| PROFINET | `profinet_asset_inventory` | DCP asset register | R | low | {asset_count, io_controller_count, assets[]} |
| SECS/GEM | `secsgem_equipment_status` | GEM link + identity (S1F1/F2) | R | low | {communication_state, are_you_there} |
| SECS/GEM | `secsgem_list_status_variables` | SVID namelist (S1F11/F12) | R | low | {count, status_variables[]} |
| SECS/GEM | `secsgem_read_status_variables` | SVID values (S1F3/F4) | R | low | {svids, values[]} |
| SECS/GEM | `secsgem_list_equipment_constants` | ECID namelist (S2F29/F30) | R | low | {count, equipment_constants[]} |
| SECS/GEM | `secsgem_read_equipment_constants` | ECID values (S2F13/F14) | R | low | {ecids, values[]} |
| SECS/GEM | `secsgem_list_alarms` | alarm list (S5F5/F6) | R | low | {count, alarms[]} |
| SECS/GEM | `secsgem_list_process_programs` | PPID directory (S7F19/F20) | R | low | {count, process_programs[]} |
| IEC-104 (energy) | `iec104_connection_info` | link + stations (CAs) | R | low | {connected, station_count, common_addresses[]} |
| IEC-104 (energy) | `iec104_interrogate` | general interrogation | R | low | {common_address, point_count, points:[{io_address, type, value, quality}]} |
| IEC-104 (energy) | `iec104_read_point` | one point by IOA | R | low | {found, io_address, value, quality} |
| DNP3 (energy) | `dnp3_link_status` | master/outstation link | R | low | {online, outstation_address, master_address} |
| DNP3 (energy) | `dnp3_integrity_poll` | Class 0/1/2/3 database | R | low | {point_count, by_type{}, points:[{type, index, value}]} |
| IEC-61850 (energy) | `iec61850_device_directory` | logical-device model | R | low | {logical_device_count, logical_devices[]} |
| IEC-61850 (energy) | `iec61850_browse` | browse model children | R | low | {reference, child_count, children[]} |
| IEC-61850 (energy) | `iec61850_read` | read data attribute (FC) | R | low | {reference, fc, value} |
| BACnet (building) | `bacnet_discover` | Who-Is device discovery | R | low | {device_count, devices:[{device_id, address}]} |
| BACnet (building) | `bacnet_object_list` | a device's objects | R | low | {object_count, objects:[{object_type, instance}]} |
| BACnet (building) | `bacnet_read_property` | one object property | R | low | {object_type, instance, property, value} |
| BACnet (building) | `bacnet_read_points` | all present-values (HVAC snapshot) | R | low | {point_count, points:[{object_type, instance, present_value}]} |
| 信创 / compliance | `compliance_mapping` | 《工控网络安全防护指南》↔ iaiops | R | low | {pillars[], status_summary, controls:[{pillar, status, gap}]} |
| 信创 / historian | `historian_push` | push telemetry to TDengine/IoTDB | R(→historian) | low | {sink, received, written, skipped_non_numeric} |
| Self | `protocols_supported` | capability map | R | low | {protocols[], diagnostics[], analytics[]} |

**90 tools** = 84 read + 6 write (MOC). The 84 reads = 67 protocol-read · 9 diagnostics · 5 analytics · 2 compliance/historian · 1 self. Run `protocols_supported()` (or `iaiops protocols`) for the live map.

---

## Per-protocol reference

### OPC-UA
- **Versions/variants**: binary `opc.tcp://` via `asyncua` (sync facade). Security: **anonymous + username/password**. Certificate message security (Sign / SignAndEncrypt) = **roadmap, not validated**.
- **Connection params**: `endpoint_url`, `username` (password encrypted), `security_mode`, `security_policy`.
- **Not supported / planned**: cert security; real Alarms & Conditions event subscriptions (alarms are surfaced best-effort by browsing alarm-like boolean nodes).

### Modbus-TCP
- **Versions/variants**: Modbus-TCP via `pymodbus`. Read function codes **FC01 (coils), FC02 (discrete), FC03 (holding), FC04 (input)**. Write FCs (**FC05/06/15/16**) = **not implemented** (read-only preview).
- **Connection params**: `host`, `port` (502), `unit_id`. Registers are untyped 16-bit words → `decode` hint (uint16/int16/uint32/int32/float32/raw); **big-endian** word order.
- **Coverage**: many domestic 国产 PLCs (汇川 Inovance / 信捷 Xinje / 和利时 Hollysys / 台达 Delta) and any Modbus-TCP vendor.

### S7comm (Siemens + 仿西门子 国产)
- **Versions/variants**: `pyS7` (**pure-Python**, ISO-on-TCP / RFC1006 — no native `libsnap7`). **S7-300/400/1200/1500** and compatible clones. Memory areas **DB / M (merker) / I / Q**. No protocol auth (CPU gates via "Permit access with PUT/GET").
- **Connection params**: `host`, `port` (102), `rack`, `slot` (0/1 for 1200/1500; 0/2 common for 300/400).
- **Write**: `s7_write_db` = **high risk_tier, MOC, dry-run default**, captures BEFORE value + undo.
- **Not supported / planned**: optimized/symbolic DB access on 1500 with "optimized block access" can require absolute-addressing config on the CPU.

### Mitsubishi MC
- **Versions/variants**: `pymcprotocol` — **MC 3E frame (binary)** only. **1E / 4E frames = not supported.** PLC types **Q / L / QnA / iQ-R / iQ-L**. Devices: D/W/R (word), M/X/Y/B (bit).
- **Connection params**: `host`, `port` (5007 default; set to the module's open MC port), `plctype`.
- **Write**: `mc_write_words` = **high/MOC/dry-run default**, captures BEFORE + undo.

### MTConnect (ALL CNC machine tools)
- **Versions/variants**: agent **REST + XML** (`requests` + `xml.etree`), namespace-agnostic (parses MTConnect 1.x Devices/Streams/Assets schemas). Endpoints: `/probe`, `/current`, `/sample`, `/assets`. **Read-only by specification.** XML parsing is hardened (DTD/entity declarations rejected — XXE/billion-laughs defense).
- **Connection params**: `agent_url` (e.g. `http://host:5000`).
- **Not supported / planned**: MTConnect streaming (long-poll `interval=`); only bounded `count=` samples.

### MQTT / Sparkplug B / UNS
- **Versions/variants**: `paho-mqtt` — **MQTT 3.1.1 & 5**. Sparkplug B topic convention `spBv1.0/{group}/{type}/{edge}/[device]` (NBIRTH/DBIRTH/NDATA/DDATA/NDEATH/DDEATH/STATE). TLS + username/password supported.
- **Full Sparkplug B decode** (no optional extra): payloads are protobuf-decoded with a *vendored, byte-for-byte* copy of the official **Eclipse Tahu** `sparkplug_b.proto` generated module (depends only on `protobuf`). Per metric you get **name, alias** (resolved to its name via the BIRTH model), **datatype** (Int8…Int64/UInt…/Float/Double/Boolean/String/DateTime/Text/UUID/**DataSet**/Bytes/File/**Template**/PropertySet…), **value**, **timestamp**, and the **`is_historical` / `is_null`** flags. A **birth/death + seq model** tracks node/device **online** state (NBIRTH/DBIRTH ↔ NDEATH/DDEATH), builds the alias→name map from BIRTH, applies NDATA/DDATA by alias, and flags **`seq` gaps / out-of-order**. **Primary-host** awareness: `STATE/<host_id>` topics surface in `sparkplug_node_list`. `sparkplug_decode_payload` decodes a single raw payload (base64/hex) offline.
- **Connection params**: `host`/`broker`, `port` (1883 / 8883 TLS), `topic`, `use_tls`, `username` (password encrypted).
- **Command**: `mqtt_publish` = **high/MOC/dry-run default**; a published command has **no automatic inverse**.

### EtherNet/IP (Rockwell / Allen-Bradley)
- **Supported**: **ControlLogix / CompactLogix** (and GuardLogix) via **CIP / EtherNet-IP** using **`pycomm3`** (pure-Python — no native deps). **Tag-based**, symbolic access: read/write tags by name (`Conveyor.Speed`, `Array[3]`, `Program:Main.X`) and **discover the controller's tag list** at runtime (`eip_list_tags`, the headline feature). `eip_controller_info` reads the controller identity.
- **Connection params**: `host`, `slot` (0 for CompactLogix; the CPU slot for a ControlLogix chassis), `port` (44818). `protocol: ethernetip` (alias `eip`).
- **Write**: `eip_write_tag` = **high risk_tier, MOC, dry-run default**, captures BEFORE value + undo.
- **Not supported / planned**: **PLC-5 / SLC-500 (PCCC)** and **Micro800** are **not supported = roadmap** (Logix tag model only).

### EtherCAT (pysoem / SOEM fieldbus master)
- **Supported**: a **real EtherCAT master** via **`pysoem`** (the Python binding for the SOEM C stack). **CoE SDO read** (`ethercat_read_sdo`, acyclic mailbox upload) + **SDO write** (`ethercat_write_sdo`, download), **input PDO read** (`ethercat_read_pdo`, one bounded cyclic snapshot), **bus scan / slave enumeration** (`ethercat_slaves`, `ethercat_slave_info` — identity, SM/FMMU mapping, object-dictionary summary), **master/working-counter state** (`ethercat_master_state`), and **AL-state transitions** INIT↔PREOP↔SAFEOP↔OP (`ethercat_set_state`).
- **HARD REQUIREMENTS** (no way around them): **Linux**, **root or `CAP_NET_RAW`**, a **dedicated NIC** cabled to the bus, and **real EtherCAT slave hardware**. `pysoem` is an **OPTIONAL extra**: `pip install iaiops[ethercat]` — the base package installs and imports **without** it, and every EtherCAT tool then **degrades to a teaching error** (never crashes, never imports pysoem at module load).
- **NOT supported**: **no software simulator** exists (unlike OPC-UA / Modbus) — EtherCAT is **hardware-only** and **not testable in mock-only CI**; **macOS is unsupported**. **EoE / FoE / SoE** mailbox protocols and full PDO-mapping decode/expansion = **roadmap**.
- **Connection params**: `nic` (the dedicated interface name, e.g. `eth1`; alias `interface`), optional `expected_slaves` (a sanity check vs the bus scan). `protocol: ethercat`.
- **Operations matrix**:

  | Tool | Op | R/W | risk | Capture/notes |
  |------|----|:---:|:----:|---------------|
  | `ethercat_master_state` | master + WKC state, slave count | R | low | expected vs found |
  | `ethercat_slaves` | bus scan / enumerate | R | low | index/vendor/product/rev/addr/AL-state |
  | `ethercat_slave_info` | one-slave detail | R | low | SM/FMMU + OD summary |
  | `ethercat_read_sdo` | CoE SDO upload | R | low | hex + uint interpretation |
  | `ethercat_read_pdo` | input PDO snapshot | R | low | single cycle, never loops |
  | `ethercat_write_sdo` | CoE SDO download | **W** | **high/MOC** | before-value (SDO read-back) + undo |
  | `ethercat_set_state` | AL-state transition | **W** | **high/MOC** | before-state + undo; **can start/stop motion** |

- **Write/state safety**: `ethercat_write_sdo` (hex little-endian bytes) and `ethercat_set_state` are **high risk_tier, MOC, dry-run by default**, capture the BEFORE value/state for undo, and need a CLI double-confirm. **Changing EtherCAT state can START or STOP machine motion** — treat with extreme care. 未经授权勿对生产控制系统写入.

### PROFINET (DCP discovery / identify — read-only)
- **Supported**: layer-2 **PROFINET-DCP** via **`pnio-dcp`** — **`profinet_discover`** (DCP IdentifyAll: one broadcast surfaces *every* station on the segment — name-of-station, MAC, IP, vendor/device id, role — closer to passive discovery than a per-device fingerprint), **`profinet_identify_station`** (by name-of-station), **`profinet_station_params`** (targeted DCP Get by MAC → name + IP suite), and **`profinet_asset_inventory`** (a register with IO-controller vs IO-device role decoding).
- **Scope (deliberate)**: **discovery + identify ONLY**. **No RT cyclic process data** (that needs an IO-controller/IO-device stack and hard real-time — out of scope and unsafe to tap), and the disruptive **DCP *Set* services** (set-name / set-ip / **blink** / factory-reset) are **intentionally not exposed** (they re-address or physically signal a live device). Ask via issue/PR to add them behind the MOC write gate.
- **HARD REQUIREMENTS**: **raw-socket access** (root / admin / `CAP_NET_RAW`) on the **NIC on the PROFINET subnet**. `pnio-dcp` is an **OPTIONAL extra**: `pip install iaiops[profinet]` — the base package installs/imports **without** it, and every tool then **degrades to a teaching error**.
- **Connection params**: `host` — **THIS machine's IP** on the PROFINET subnet (the DCP broadcast goes out on it). `protocol: profinet`.
- **Preview caveat**: validated against a **mocked `pnio-dcp` DCP** — **not** verified against live PROFINET devices yet.

### Energy edition (electrical substation / utility telecontrol — read-only)
The **energy** vertical adds the three protocols that dominate power/utility SCADA, as **read-only monitoring** taps. Install with `pip install iaiops[energy]` and expose with `IAIOPS_MCP=energy`.
- **IEC 60870-5-104** (`c104`): `iec104_connection_info` (link + discovered ASDU common addresses), `iec104_interrogate` (general interrogation — all monitored points of a station), `iec104_read_point` (one point by IOA). Config: `host` / `port` (2404) / `common_address`.
- **DNP3** (`pydnp3`/opendnp3): `dnp3_link_status` (master/outstation link), `dnp3_integrity_poll` (Class 0/1/2/3 → the outstation database, grouped by binary/analog/counter). Config: `host` / `port` (20000) / `unit_id` (outstation addr) / `master_address`.
- **IEC 61850 MMS** (`libiec61850` binding): `iec61850_device_directory` (logical-device model map), `iec61850_browse` (browse LD/LN/DO children), `iec61850_read` (read a data attribute by object-reference + functional constraint, e.g. `IED1MMXU1.TotW.mag.f` FC=`MX`). Config: `host` / `port` (102).
- **Scope (deliberate)**: **monitor direction only** — control commands (IEC-104 C_SC/C_DC/setpoints, DNP3 CROB/analog-output, IEC-61850 Oper/select-before-operate) and IEC-61850 GOOSE / Sampled Values are **not exposed**.
- **⚠️ Preview / 待核实**: the energy connectors are **mock-tested** and their **library/API bindings are unverified against live RTUs/IEDs**. `iec61850` needs **libiec61850** built; `pydnp3` builds a native extension — these stay opt-in (not in `iaiops[all]`). This is the connector line's largest validation debt — open an issue with your device + library version if a binding symbol differs.

### Building edition (facility / HVAC / 厂务 — read-only)
The **building** vertical adds **BACnet/IP** (ASHRAE 135) — the dominant building-automation protocol for HVAC, lighting, metering, and facility plant. Install with `pip install iaiops[building]` and expose with `IAIOPS_MCP=building`.
- **BACnet/IP** (`BAC0` over bacpypes3): `bacnet_discover` (Who-Is device discovery), `bacnet_object_list` (a device's objects), `bacnet_read_property` (one object property), `bacnet_read_points` (present-value of all analog/binary/multistate points — the HVAC snapshot). Config: `host` = THIS machine's BACnet/IP interface (`ip` or `ip/mask`) / `port` (47808).
- **Scope (deliberate)**: **read-only** — present-value writes (with priority/relinquish) are not exposed; overriding a live building-control point is OT-dangerous.
- **⚠️ Preview / 待核实**: mock-tested; the BAC0 binding is **unverified against live building gear**.

### 信创 / China entry (offline · 国产 TSDB · compliance)
For 自主可控 / 信创 deployments — see **[docs/CHINA.md](docs/CHINA.md)** for the full guide.
- **Air-gapped install**: pure-Python core + per-protocol optional extras → install from a local wheelhouse with `pip install --no-index --find-links ./wheelhouse "iaiops[...]"`; secrets stay local (encrypted store), no cloud KMS.
- **National TSDB historian sink** (`historian_push`, CLI `iaiops historian push`): write collected telemetry to **TDengine** (`iaiops[tdengine]`) or **Apache IoTDB** (`iaiops[iotdb]`) — domestic, controllable; we don't build our own store or bind InfluxDB. *Data egress to the operator's own historian, not a control write.*
- **Compliance mapping** (`compliance_mapping`, CLI `iaiops compliance`): an honest 《工控系统网络安全防护指南》 ↔ iaiops self-assessment across 分区隔离 / 可审计 / 双向认证 / 最小权限 / 数据保护 / 自主可控, with per-control status (addressed / partial / 待核实) and the named gap.
- **国产 PLC**: 汇川 / 台达 / 信捷 over the existing **Modbus-TCP / S7** connectors.
- **⚠️ 待核实**: 国产 OS (麒麟/统信) · 芯 (鲲鹏/海光) · PLC validation and the TSDB write paths are documented but **not yet hardware-verified** — see the validation matrix in docs/CHINA.md.

### OEE / downtime analytics (cross-protocol, read-only)
- `oee_compute` — **OEE = Availability × Performance × Quality** from production inputs (planned time, run time, ideal cycle, total/good counts). Each factor is reported **raw + clamped to [0,1]**; a `capped` performance >1.0 flags an optimistic ideal cycle.
- `downtime_events` — auto-detects **running→stopped transitions** in a `{timestamp, state}` series and produces stoppage events with durations, **categorized** (changeover / material / mechanical / quality / break / unknown, by keyword heuristics or a `{state: category}` override).
- `oee_multidim` — aggregates OEE across **machine × part × shift** (or any dimensions) from labelled records → the matrix + worst performers.
- Operate over **provided/collected inputs** (fully testable without a plant). `mtconnect_oee_snapshot` surfaces the live MTConnect availability/execution inputs that feed these.

### Active asset inventory / fingerprint (read-only)
- `asset_inventory` — for each configured (or named) endpoint, **actively connects** with our own protocol client and reads its **identity** call (S7 `s7_cpu_info`, EtherNet/IP `eip_controller_info`, OPC-UA server build info, Modbus **Device Identification FC43/0x2B**, Mitsubishi CPU type, MTConnect device model), aggregating **vendor / model / firmware / serial / reachable / last_seen** into an asset register.
- **Honest scope (IEC 62443-flavored)**: this is **ACTIVE fingerprinting via our client connections**, **NOT** passive SPAN/tap discovery — it only finds devices we are configured to reach and adds light load to each. **Passive, traffic-mirroring discovery is roadmap.**

### OPC-UA Historical Access (HDA)
- `opcua_read_history` — reads stored historical values for a node over a `[start,end]` ISO-8601 window via the server's **HistoryRead** service (`asyncua` `read_raw_history`), **bounded** by `max_points` (≤2000). Returns `{supported:false, note}` **gracefully** when the server does not historize the node (no crash). Read-only.

### Change-of-value (CoV) monitor
- `monitor_changes` — bounded **deadband report**: polls a point and returns **only the value CHANGES** (with timestamps), not every sample. Works over **OPC-UA / Modbus / S7 / Mitsubishi MC / EtherNet-IP**. **Never an infinite loop** — hard-capped by both `duration_s` (≤120) and `max_changes` (≤500). Read-only.

---

## Install

Protocol client libraries are **optional extras** — install only the 1–2 protocols a site
actually runs (every protocol library is imported lazily; the base package installs and
imports without any of them, and a call to a not-installed protocol returns a teaching
error pointing at the right extra):

```bash
uv tool install "iaiops[opcua,modbus]"   # just the protocols you need
# or one per site:  pip install "iaiops[s7]"   ·   everything:  pip install "iaiops[all]"
# or a per-industry edition bundle:        pip install "iaiops[fab]"

iaiops init                 # interactive: add endpoints, store passwords encrypted
iaiops doctor               # config + per-protocol connectivity probe (point at simulators)
iaiops protocols            # the capability map
```

Protocol extras: `opcua` · `modbus` · `s7` · `mc` · `eip` · `mtconnect` · `sparkplug` · `secsgem` · `ethercat` · `all`.

**Edition bundles** (match the same-named `IAIOPS_MCP` profiles — install the protocols a vertical runs):
`fab` (secsgem + opcua + s7 + modbus) · `factory` (the discrete-manufacturing set — all protocols except SECS/GEM) · `process` (opcua + modbus). Energy/building bundles arrive with their signature protocols (IEC-104/DNP3/61850, BACnet).

### Master password
Secrets (per-endpoint passwords, MQTT credentials) are **never** stored in plaintext — they live in `~/.iaiops/secrets.enc` (Fernet + scrypt). Export `IAIOPS_MASTER_PASSWORD` so the MCP server/CLI can unlock non-interactively:
```bash
export IAIOPS_MASTER_PASSWORD='…'
```

### Example `~/.iaiops/config.yaml` (one block per protocol)
```yaml
endpoints:
  - name: line1
    protocol: opcua
    endpoint_url: opc.tcp://plc.lan:4840
    # username: operator           # password stored encrypted via init/secret set
    tags:
      - { ref: "ns=2;i=5", label: temp, warn_high: 70, alarm_high: 90 }
  - name: plc2
    protocol: modbus
    host: 10.0.0.5
    port: 502
    unit_id: 1
  - name: press1
    protocol: s7
    host: 10.0.0.6
    rack: 0
    slot: 1                        # S7-1200/1500
  - name: cell3
    protocol: mc
    host: 10.0.0.7
    port: 5007
    plctype: iQ-R
  - name: vmc1
    protocol: mtconnect
    agent_url: http://10.0.0.8:5000
  - name: uns
    protocol: mqtt
    host: broker.lan
    use_tls: true                  # → port 8883
    topic: spBv1.0/#
    # username: edge1              # password stored encrypted
  - name: cell5
    protocol: ethernetip           # alias: eip
    host: 10.0.0.9
    slot: 0                        # 0 for CompactLogix; CPU slot for ControlLogix
  - name: bus1
    protocol: ethercat             # Linux + root/CAP_NET_RAW + pip install iaiops[ethercat]
    nic: eth1                      # dedicated NIC cabled to the EtherCAT bus
    expected_slaves: 8             # optional sanity check vs the bus scan
```

### `iaiops init` walkthrough (per protocol)
```
$ iaiops init
Step 1 — master password: ********
Step 2 — add an endpoint
  Endpoint name (e.g. line1): press1
  Protocol ('opcua','modbus','s7','mc','mtconnect','mqtt') [opcua]: s7
  S7 PLC host (IP/FQDN): 10.0.0.6
  Port [102]: 102
  Rack (0 for S7-1200/1500) [0]: 0
  Slot (1 for S7-1200/1500, 2 for S7-300/400) [1]: 1
✓ Saved endpoint 'press1'.
```
(MQTT prompts add TLS/topic/username; MTConnect prompts for `agent_url`; EtherCAT prompts for the `nic` + `expected_slaves` and warns about the Linux/root/NIC/optional-extra requirement; OPC-UA/MQTT prompt for a hidden password stored encrypted.)

### Test against a simulator (per protocol)
- **OPC-UA** — an `asyncua` demo server (the test suite runs a real in-process one).
- **Modbus** — ModbusPal or a `pymodbus` server simulator.
- **S7** — a pyS7/snap7 S7 server sim (Snap7 server) on `:102`.
- **MTConnect** — the public MTConnect demo agent, or a local agent.
- **MQTT** — a local `mosquitto` broker (+ a Sparkplug edge for SpB topics).
- **Mitsubishi MC** — GX Simulator / an MC 3E server sim.
- **EtherNet/IP** — a pycomm3-compatible CIP/Logix simulator (or a spare CompactLogix).
- **EtherCAT** — **no simulator exists** (hard-real-time, raw-Ethernet). Validate only on **Linux**, as **root / with `CAP_NET_RAW`**, on a **dedicated NIC** wired to **real slaves** (e.g. a Beckhoff EK1100 coupler + EL terminals). `iaiops doctor` reports a clear "needs Linux/root/NIC/pysoem" status off the bus rather than failing.

---

## Usage

### CLI (read)
```bash
iaiops opcua read "ns=2;i=5" -e line1
iaiops modbus holding 0 -e plc2 --count 4 --decode float32
iaiops s7 read-db 1 REAL 4 -e press1 --count 2
iaiops mc words D100 -e cell3 --count 8
iaiops mtconnect oee -e vmc1
iaiops mqtt nodes -e uns --timeout-s 15
iaiops eip tags -e cell5                           # Logix tag discovery
iaiops eip read "Conveyor.Speed" -e cell5
iaiops ethercat slaves -e bus1                     # EtherCAT bus scan (Linux+root)
iaiops ethercat read-sdo 0 4120 --subindex 1 -e bus1   # CoE SDO 0x1018:1
iaiops opcua history "ns=2;i=5" -e line1 --start 2026-06-28T08:00:00Z   # HDA
iaiops opcua monitor "ns=2;i=5" -e line1 --duration-s 20 --deadband 0.5 # CoV
iaiops diag dataflow -e line1 --ref "ns=2;i=5" --freshness-s 30
iaiops analytics oee 28800 25200 2.0 12000 11800   # OEE = A×P×Q
iaiops analytics asset -e press1 -e cell5           # active asset register
```

### CLI (write — dry-run by default, double-confirm on `--apply`)
```bash
iaiops s7 write-db 1 INT 0 42 -e press1            # dry-run preview
iaiops s7 write-db 1 INT 0 42 -e press1 --apply    # double-confirm prompt
iaiops mqtt publish factory/line1/cmd '{"setpoint":50}' -e uns --apply
iaiops eip write-tag Setpoint 42 -e cell5 --apply  # Logix tag write (double-confirm)
iaiops ethercat write-sdo 0 24698 e8030000 -e bus1 --apply   # CoE SDO 0x607A download
iaiops ethercat set-state PREOP --slave 0 -e bus1 --apply     # AL-state (can stop motion!)
```

### MCP tool calls (JSON args → sample structured return)

`s7_read_db`:
```json
{ "db": 1, "dtype": "REAL", "start": 4, "endpoint": "press1", "count": 2 }
```
```json
{ "endpoint": "press1", "area": "DB", "db": 1, "dtype": "REAL", "start": 4,
  "count": 2, "items": [ {"address": "DB1,REAL4", "value": 20.5},
                         {"address": "DB1,REAL8", "value": 4.2} ] }
```

`s7_write_db` (dry-run):
```json
{ "db": 1, "dtype": "INT", "start": 0, "value": 42, "endpoint": "press1" }
```
```json
{ "address": "DB1,INT0", "dry_run": true, "before": 7, "would_write": 42,
  "note": "Dry run — nothing written. Re-run with dry_run=false AND a recorded approver…" }
```

`mtconnect_oee_snapshot`:
```json
{ "availability": "AVAILABLE", "execution": "ACTIVE", "controller_mode": "AUTOMATIC",
  "program": "O1234", "available": true, "running": true, "verdict": "running" }
```

`eip_read_tag`:
```json
{ "tag": "Conveyor.Speed", "endpoint": "cell5" }
```
```json
{ "endpoint": "cell5", "tag": "Conveyor.Speed", "value": 1500.0, "type": "REAL",
  "error": "", "good": true }
```

`eip_write_tag` (dry-run):
```json
{ "tag": "Setpoint", "value": 42, "endpoint": "cell5" }
```
```json
{ "endpoint": "cell5", "tag": "Setpoint", "dry_run": true, "before": 7,
  "would_write": 42, "note": "Dry run — nothing written. Re-run with dry_run=false AND a recorded approver…" }
```

`ethercat_read_sdo` (CoE SDO upload):
```json
{ "slave": 0, "index": 4120, "subindex": 1, "endpoint": "bus1" }
```
```json
{ "endpoint": "bus1", "slave": 0, "index": "0x1018", "subindex": 1,
  "byte_length": 4, "hex": "9a020000", "as_uint": 666 }
```

`ethercat_set_state` (dry-run; can start/stop motion):
```json
{ "state": "OP", "slave": 0, "endpoint": "bus1" }
```
```json
{ "endpoint": "bus1", "scope": "slave[0]", "dry_run": true, "before": "SAFEOP",
  "would_request": "OP", "note": "Dry run — no state change. … Changing EtherCAT state can start/stop machine motion." }
```

`sparkplug_decode_payload` (full SpB metric decode):
```json
{ "payload": "CAESBwoDYWJjEAE=", "encoding": "base64" }
```
```json
{ "encoding": "sparkplug_b", "seq": 0, "metric_count": 2, "historical_count": 0,
  "metrics": [ {"name": "Temperature", "alias": 1, "datatype": "Double", "value": 21.5,
                "is_historical": false, "is_null": false} ] }
```

`oee_compute`:
```json
{ "planned_time_s": 28800, "run_time_s": 25200, "ideal_cycle_time_s": 2.0,
  "total_count": 12000, "good_count": 11800 }
```
```json
{ "availability": {"raw": 0.875, "value": 0.875, "capped": false},
  "performance": {"value": 0.952381}, "quality": {"value": 0.983333},
  "oee": 0.819444, "oee_pct": 81.94 }
```

`asset_inventory` (active fingerprint):
```json
{ "endpoints": ["press1", "cell5"] }
```
```json
{ "asset_count": 2, "reachable_count": 2, "method": "active_fingerprint",
  "assets": [ {"endpoint": "press1", "protocol": "s7", "vendor": "Siemens/compatible",
               "model": "CPU 1511-1 PN", "firmware": "2.8", "reachable": true,
               "last_seen": "2026-06-28T10:00:00+00:00"} ] }
```

### Diagnostics (multi-dimensional JSON for an agent to visualize)

`diagnose_dataflow(endpoint="line1", ref="ns=2;i=5", freshness_threshold_s=30)`:
```json
{ "verdict": "comms_ok_value_stale",
  "diagnosis": "Connected with good status, but the value is STALE (age 412s > 30s) — the source/field upstream has stopped updating this point.",
  "recommended_action": "Trace upstream: the device serves the last value fine, so suspect the source/scanner/field signal that should refresh it.",
  "hops": [ {"hop":"connect","protocol":"opcua","ok":true,"detail":"OPC-UA state=0"},
            {"hop":"read_tag","ref":"ns=2;i=5","ok":true,"detail":"5.0"},
            {"hop":"freshness","evaluated":true,"stale":true,"age_seconds":412.0} ] }
```

`alarm_bad_actors(events=[…])`:
```json
{ "event_count": 55, "window_minutes": 0.82, "alarms_per_hour": 4024.4,
  "isa_18_2": {"ok_max":6,"manageable_max":12,"flood_min":30},
  "flood_verdict": "flood",
  "priority_distribution": {"high":50,"low":5},
  "pareto_sources_for_80pct": ["FIC101"],
  "top_offenders": [ {"source":"FIC101","count":50,"share_pct":90.9,"chattering":true,"standing":false} ],
  "chattering": ["FIC101"], "standing": [] }
```

`tag_health(tags=[…])`:
```json
{ "evaluated": 4, "overall": "alarm", "offender_count": 3,
  "offenders": [ {"ref":"hot","latest":99,"flags":["out_of_range_alarm"],"severity":3},
                 {"ref":"flat","latest":5,"flags":["flatline"],"severity":2},
                 {"ref":"bad","latest":null,"flags":["bad_quality"],"severity":3} ] }
```

#### AI downtime root-cause copilot (flagship)

`downtime_root_cause` correlates whatever evidence you can hand over — alarm
events, tag samples, a `diagnose_dataflow` verdict, a machine-state series —
around an incident window and returns an **evidence-cited, advisory** verdict.
Read-first: it proposes a human-approved, MOC-gated, undoable action and executes
nothing. Anti-hallucination by design — it cites only signals actually present in
the input, weights them by temporal proximity to onset (a cause precedes its
effect), and downgrades to `insufficient_evidence` (with a `recommended_next_data`
list) rather than guessing when evidence is thin.

`downtime_root_cause(window={"start":"2026-06-28T10:00:00Z","asset":"line1"},
alarms=[{"source":"M1_DRIVE","timestamp":"2026-06-28T09:59:52Z","message":"motor overload trip"}],
tags=[{"ref":"DRV1.Torque","samples":[10,11,99,99],"alarm_high":80}], dataflow={"verdict":"healthy"})`:
```json
{ "window": {"start":"2026-06-28 10:00:00+00:00","asset":"line1","duration_s":300.0},
  "verdict": "root_cause_identified",
  "primary_cause": {
    "cause": "mechanical_fault", "confidence": 0.722, "confidence_band": "high",
    "evidence": [
      {"signal":"alarm","ref":"M1_DRIVE","at":"2026-06-28 09:59:52+00:00","lead_time_s":8.0,
       "detail":"motor overload trip","weight":0.4959},
      {"signal":"tag","ref":"DRV1.Torque","detail":"flags=out_of_range_alarm severity=3","weight":0.45} ],
    "recommended_action": "Dispatch maintenance to inspect the faulting unit; if a latch/interlock is set, the reversible step is to clear the fault and reset the latch (MOC-approved, undo captures the prior latch state)." },
  "evidence_summary": {"alarms_supplied":1,"tags_supplied":1,"dataflow_verdict":"healthy","total_evidence_items":2},
  "anti_hallucination": "Advisory only — nothing is executed. Every cited signal is present in the supplied evidence …" }
```

The same copilot is on the CLI: `iaiops diag rca --input bundle.json` where the
bundle is `{window, alarms?, tags?, dataflow?, state_series?}`.

**Let it gather its own evidence.** `downtime_root_cause_live` (CLI `iaiops diag
rca-live`) takes just an endpoint + window + the refs to look at, then pulls the
evidence itself — a cross-protocol `diagnose_dataflow` probe, a short sampled
series per ref (so flatline / bad-quality / anomaly surface via `tag_health`),
and active OPC-UA conditions — before running the same advisory, read-only copilot.
The gathered bundle is echoed back under `collected_evidence` (no hidden inputs):

```bash
iaiops diag rca-live -e line1 --start 2026-06-28T10:00:00Z \
  --asset line1 --ref "ns=2;i=5" --ref "ns=2;i=6"
```

### Data-quality watchdog & UNS governance (read-only intelligence)
Two more pure-analysis layers — fully testable without live gear, and they feed the RCA copilot.
- **`data_quality_scorecard`** (CLI `iaiops diag dataquality`) — a fleet **data-TRUST** rollup: scores each tag 0-100 on whether its data can be *believed* — staleness, **dead heartbeat** (first-class), bad-quality, flatline, gaps, anomaly — then rolls up per endpoint and across the fleet with an issue breakdown and ranked worst offenders. Distinct from process health: it asks "can I trust this number," not "is this number alarming." `heartbeat_health` (CLI `iaiops diag heartbeat`) is the standalone watchdog-liveness check (a flatlined heartbeat = dead upstream even when comms look fine).
- **`uns_topic_audit`** (CLI `iaiops mqtt uns-audit`) — governs a UNS topic tree: naming conformance (allowed roots / min depth) + **topic sprawl** (casing collisions of the same logical name, leaf metrics scattered under many parents, depth outliers, duplicates) → a `clean`/`minor`/`sprawling` verdict. **`uns_schema_drift`** (CLI `iaiops mqtt uns-drift`) — compares two Sparkplug NBIRTH-style snapshots and classifies the change `none` / `additive` / `breaking` (a metric removed or its datatype changed). Positions the UNS as a *governable* neutral data source, not just a broker.

### MCP server
```bash
iaiops mcp        # stdio transport; or the `iaiops-mcp` entry point
```

**Menu — expose only the protocols a site runs.** A fab usually runs 1–2 protocols;
exposing all 13 floods the model with tools it can't use. Set `IAIOPS_MCP` to a
comma-list of protocols and/or a named profile (default `all`). The cross-protocol
brain (OEE / downtime / diagnostics / asset / analysis) is **always** exposed.

```bash
IAIOPS_MCP=opcua,modbus iaiops-mcp   # 32 tools instead of 90
IAIOPS_MCP=fab          iaiops-mcp   # named profile (opcua+s7+modbus)
IAIOPS_MCP=opcua        iaiops-mcp   # effectively a single-protocol MCP
```

**Named entry-point sugar.** For the common single-protocol / single-edition case
there is a pre-scoped console script per protocol and per named profile — no env
var to set. Each is a thin shim over the same server:

```bash
iaiops-mcp-opcua     # == IAIOPS_MCP=opcua    iaiops-mcp
iaiops-mcp-modbus    # == IAIOPS_MCP=modbus   iaiops-mcp
iaiops-mcp-fab       # == IAIOPS_MCP=fab      iaiops-mcp  (per-edition)
iaiops-mcp-energy    # == IAIOPS_MCP=energy   iaiops-mcp
iaiops-mcp-building  # == IAIOPS_MCP=building iaiops-mcp
```

Named profiles: `all` · `fab` · `factory` · `process` · `energy` · `building`. In an
MCP client (e.g. Claude Desktop) set `IAIOPS_MCP` per server entry — or point the
entry straight at the matching `iaiops-mcp-<name>` script — one entry per site/line,
each a lean single- or dual-protocol server.

---

## Safety & governance

- **Read-first.** 84 of 90 tools are read-only. The 6 write/command tools (`s7_write_db`, `mc_write_words`, `mqtt_publish`, `eip_write_tag`, `ethercat_write_sdo`, `ethercat_set_state`) are **OT-dangerous**: governed at **high risk_tier**, **off by default (dry-run)**, capture the **BEFORE value/state for undo**, require a **double-confirm in the CLI**, and (via policy) a recorded approver — **MOC discipline**. **`ethercat_set_state` can START or STOP machine motion.** 未经授权勿对生产控制系统写入.
- **Do not point this at a production control system without authorization.** OT networks are safety-critical; even reads add load. Test against a simulator first.
- All endpoint-returned text is sanitized (prompt-injection defense); secrets are never returned by any tool; MTConnect XML is parsed with DTD/entity declarations refused.
- Every tool runs through the vendored governance harness: SQLite **audit** (`~/.iaiops/audit.db`), token/call **budget** + runaway breaker, **risk-tier** gate, **undo** recording.

## Roadmap

- EtherNet/IP **PLC-5 / SLC-500 (PCCC)** and **Micro800** support (Logix tags are done in 0.2.0).
- **Passive** asset discovery (SPAN/tap, no connections) alongside today's active fingerprint.
- EtherCAT **EoE / FoE / SoE** mailbox protocols and full PDO-mapping decode (CoE SDO/PDO read+write and AL-state landed in 0.3.0 via the optional `pysoem` extra).
- OPC-UA certificate security + real Alarms & Conditions subscriptions.
- MTConnect streaming long-poll; Sparkplug B DataSet/Template deep expansion.

**Missing a protocol, device, or feature? 缺功能提 issue/PR 欢迎留言** — open a [GitHub issue or PR](https://github.com/industrial-aiops/industrial-aiops/issues).

## License

MIT © wei