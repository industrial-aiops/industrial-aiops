<!-- mcp-name: io.github.industrial-aiops/iaiops -->

# Industrial-AIOps

**Governed, vendor-neutral industrial data tap + intelligent troubleshooting for AI agents — across OPC-UA (incl. Historical Access), Modbus-TCP, S7comm, Mitsubishi MC, MTConnect, MQTT/Sparkplug B (full decode), EtherNet/IP (Rockwell/Allen-Bradley Logix), EtherCAT (pysoem/SOEM fieldbus master), and SECS/GEM (HSMS fab equipment) — plus OEE/downtime, active asset-inventory, and change-of-value analytics.**

Industrial-AIOps is the OT/industrial member of [Industrial-AIOps](https://github.com/industrial-aiops). It is a **factory-level, vendor-neutral, governed data tap** that lets an AI agent safely *read* industrial control systems across many field protocols, plus a **cross-protocol intelligence layer** that localizes "no data" breaks, analyzes alarm floods (ISA-18.2), ranks unhealthy tags, computes OEE / categorizes downtime, and builds an active asset register. Read-first by design; the few write/command paths are OT-dangerous and gated by MOC discipline. Every tool runs through a vendored governance harness (audit / budget / risk-tier / undo).

> ⚠️ **Preview / v0.3.0** — validated against an **in-process OPC-UA simulator (incl. HDA), mocked Modbus/S7/Mitsubishi/EtherNet-IP(pycomm3)/EtherCAT(pysoem)/SECS-GEM(secsgem) clients, static MTConnect XML fixtures, and synthetic MQTT/Sparkplug B protobuf payloads**. **NOT tested against live PLCs / SCADA / brokers / Logix controllers / EtherCAT slaves.** EtherCAT is hard-real-time and has **no software simulator** (Linux + root + a real bus only), so it is **entirely unverified against hardware**. See *Safety*.

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
| SECS/GEM | `secsgem_equipment_status` | GEM link + identity (S1F1/F2) | R | low | {communication_state, are_you_there} |
| SECS/GEM | `secsgem_list_status_variables` | SVID namelist (S1F11/F12) | R | low | {count, status_variables[]} |
| SECS/GEM | `secsgem_read_status_variables` | SVID values (S1F3/F4) | R | low | {svids, values[]} |
| SECS/GEM | `secsgem_list_equipment_constants` | ECID namelist (S2F29/F30) | R | low | {count, equipment_constants[]} |
| SECS/GEM | `secsgem_read_equipment_constants` | ECID values (S2F13/F14) | R | low | {ecids, values[]} |
| SECS/GEM | `secsgem_list_alarms` | alarm list (S5F5/F6) | R | low | {count, alarms[]} |
| SECS/GEM | `secsgem_list_process_programs` | PPID directory (S7F19/F20) | R | low | {count, process_programs[]} |
| Self | `protocols_supported` | capability map | R | low | {protocols[], diagnostics[], analytics[]} |

**66 tools** = 60 read + 6 write (MOC). The 60 reads = 49 protocol-read · 5 diagnostics · 5 analytics · 1 self. Run `protocols_supported()` (or `iaiops protocols`) for the live map.

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
`fab` (secsgem + opcua + s7 + modbus) · `factory` (the discrete-manufacturing set) · `process` (opcua + modbus). Energy/building bundles arrive with their signature protocols (IEC-104/DNP3/61850, BACnet).

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

### MCP server
```bash
iaiops mcp        # stdio transport; or the `iaiops-mcp` entry point
```

**Menu — expose only the protocols a site runs.** A fab usually runs 1–2 protocols;
exposing all 8 floods the model with tools it can't use. Set `IAIOPS_MCP` to a
comma-list of protocols and/or a named profile (default `all`). The cross-protocol
brain (OEE / downtime / diagnostics / asset / analysis) is **always** exposed.

```bash
IAIOPS_MCP=opcua,modbus iaiops-mcp   # 26 tools instead of 66
IAIOPS_MCP=fab          iaiops-mcp   # named profile (opcua+s7+modbus)
IAIOPS_MCP=opcua        iaiops-mcp   # effectively a single-protocol MCP
```

Named profiles: `all` · `fab` · `factory` · `process`. In an MCP client (e.g. Claude
Desktop) set `IAIOPS_MCP` per server entry — one entry per site/line, each a lean
single- or dual-protocol server.

---

## Safety & governance

- **Read-first.** 60 of 66 tools are read-only. The 6 write/command tools (`s7_write_db`, `mc_write_words`, `mqtt_publish`, `eip_write_tag`, `ethercat_write_sdo`, `ethercat_set_state`) are **OT-dangerous**: governed at **high risk_tier**, **off by default (dry-run)**, capture the **BEFORE value/state for undo**, require a **double-confirm in the CLI**, and (via policy) a recorded approver — **MOC discipline**. **`ethercat_set_state` can START or STOP machine motion.** 未经授权勿对生产控制系统写入.
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