<!-- mcp-name: io.github.AIops-tools/ot-aiops -->

# OT-AIops

**Governed, vendor-neutral industrial data tap + intelligent troubleshooting for AI agents — across OPC-UA, Modbus-TCP, S7comm, Mitsubishi MC, MTConnect, and MQTT/Sparkplug B.**

OT-AIops is the OT/industrial member of [AIops-tools](https://github.com/AIops-tools). It is a **factory-level, vendor-neutral, governed data tap** that lets an AI agent safely *read* industrial control systems across many field protocols, plus a **cross-protocol intelligence layer** that localizes "no data" breaks, analyzes alarm floods (ISA-18.2), and ranks unhealthy tags. Read-first by design; the few write/command paths are OT-dangerous and gated by MOC discipline. Every tool runs through a vendored governance harness (audit / budget / risk-tier / undo).

> ⚠️ **Preview / v0.1.0** — validated against an **in-process OPC-UA simulator, mocked Modbus/S7/Mitsubishi clients, static MTConnect XML fixtures, and synthetic MQTT/Sparkplug payloads**. **NOT tested against live PLCs / SCADA / brokers.** See *Safety*.

## Why

OT is exactly where you want an agent on a tight leash: read first, never blind-write. OT-AIops is the **safe, neutral read wedge** — one package, one MCP server, many protocols — with governance and an intelligence layer that turns raw reads into actionable diagnoses.

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
| MQTT/Sparkplug | `sparkplug_subscribe_sample` | bounded SpB sample | R | low | {samples:[{sparkplug, payload}]} |
| MQTT/Sparkplug | `sparkplug_node_list` | node discovery | R | low | {nodes:[{group_id, edge_node_id, devices}]} |
| MQTT/Sparkplug | `uns_browse` | topic-tree browse | R | low | {topics[], tree{}} |
| MQTT/Sparkplug | `mqtt_publish` | publish/command | **W** | **high/MOC** | {published_bytes, applied} |
| Diagnostics | `diagnose_dataflow` | localize no-data | R | low | {verdict, diagnosis, hops[]} |
| Diagnostics | `alarm_bad_actors` | ISA-18.2 flood | R | low | {flood_verdict, top_offenders[]} |
| Diagnostics | `tag_health` | offender ranking | R | low | {overall, offenders[]} |
| Diagnostics | `historian_health` | gap/flatline | R | low | {verdict, gaps[]} |
| Self | `protocols_supported` | capability map | R | low | {protocols[], diagnostics[]} |
| Roadmap | `ethernetip_status` | Rockwell stub | R | low | {implemented:false, suggested_dependency} |
| Roadmap | `ethercat_status` | EtherCAT stub | R | low | {implemented:false, suggested_dependency} |

**40 tools** = 33 read · 3 write (MOC) · 4 diagnostics. Run `protocols_supported()` (or `ot-aiops protocols`) for the live map.

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
- **Versions/variants**: `paho-mqtt` — **MQTT 3.1.1 & 5**. Sparkplug B topic convention `spBv1.0/{group}/{type}/{edge}/[device]` (NBIRTH/DBIRTH/NDATA/DDATA…). Sparkplug **protobuf payloads decode when an optional decoder (`tahu`) is installed**, else reported as binary with a hex preview + hint (JSON/text payloads always decode). TLS + username/password supported.
- **Connection params**: `host`/`broker`, `port` (1883 / 8883 TLS), `topic`, `use_tls`, `username` (password encrypted).
- **Command**: `mqtt_publish` = **high/MOC/dry-run default**; a published command has **no automatic inverse**.

### EtherNet/IP (Rockwell / Allen-Bradley) — roadmap stub
- `ethernetip_status` returns a clear "not implemented" + roadmap. Planned lib: **`pycomm3`** (pure-Python Logix tags). Not bundled to keep the install light.

### EtherCAT — roadmap stub
- `ethercat_status` returns a clear "not implemented" + roadmap. Needs a master stack (**`pysoem`/SOEM**) + a dedicated NIC + slave devices.

---

## Install

```bash
uv tool install ot-aiops      # or: pip install ot-aiops
ot-aiops init                 # interactive: add endpoints, store passwords encrypted
ot-aiops doctor               # config + per-protocol connectivity probe (point at simulators)
ot-aiops protocols            # the capability map
```

### Master password
Secrets (per-endpoint passwords, MQTT credentials) are **never** stored in plaintext — they live in `~/.ot-aiops/secrets.enc` (Fernet + scrypt). Export `OT_AIOPS_MASTER_PASSWORD` so the MCP server/CLI can unlock non-interactively:
```bash
export OT_AIOPS_MASTER_PASSWORD='…'
```

### Example `~/.ot-aiops/config.yaml` (one block per protocol)
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
```

### `ot-aiops init` walkthrough (per protocol)
```
$ ot-aiops init
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
(MQTT prompts add TLS/topic/username; MTConnect prompts for `agent_url`; OPC-UA/MQTT prompt for a hidden password stored encrypted.)

### Test against a simulator (per protocol)
- **OPC-UA** — an `asyncua` demo server (the test suite runs a real in-process one).
- **Modbus** — ModbusPal or a `pymodbus` server simulator.
- **S7** — a pyS7/snap7 S7 server sim (Snap7 server) on `:102`.
- **MTConnect** — the public MTConnect demo agent, or a local agent.
- **MQTT** — a local `mosquitto` broker (+ a Sparkplug edge for SpB topics).
- **Mitsubishi MC** — GX Simulator / an MC 3E server sim.

---

## Usage

### CLI (read)
```bash
ot-aiops opcua read "ns=2;i=5" -e line1
ot-aiops modbus holding 0 -e plc2 --count 4 --decode float32
ot-aiops s7 read-db 1 REAL 4 -e press1 --count 2
ot-aiops mc words D100 -e cell3 --count 8
ot-aiops mtconnect oee -e vmc1
ot-aiops mqtt nodes -e uns --timeout-s 15
ot-aiops diag dataflow -e line1 --ref "ns=2;i=5" --freshness-s 30
```

### CLI (write — dry-run by default, double-confirm on `--apply`)
```bash
ot-aiops s7 write-db 1 INT 0 42 -e press1            # dry-run preview
ot-aiops s7 write-db 1 INT 0 42 -e press1 --apply    # double-confirm prompt
ot-aiops mqtt publish factory/line1/cmd '{"setpoint":50}' -e uns --apply
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
ot-aiops mcp        # stdio transport; or the `ot-aiops-mcp` entry point
```

---

## Safety & governance

- **Read-first.** 33 of 36 protocol tools are read-only. The 3 write/command tools (`s7_write_db`, `mc_write_words`, `mqtt_publish`) are **OT-dangerous**: governed at **high risk_tier**, **off by default (dry-run)**, capture the **BEFORE value for undo**, require a **double-confirm in the CLI**, and (via policy) a recorded approver — **MOC discipline**. 未经授权勿对生产控制系统写入.
- **Do not point this at a production control system without authorization.** OT networks are safety-critical; even reads add load. Test against a simulator first.
- All endpoint-returned text is sanitized (prompt-injection defense); secrets are never returned by any tool; MTConnect XML is parsed with DTD/entity declarations refused.
- Every tool runs through the vendored governance harness: SQLite **audit** (`~/.ot-aiops/audit.db`), token/call **budget** + runaway breaker, **risk-tier** gate, **undo** recording.

## Roadmap

- EtherNet/IP read-first Logix tags via an optional `pycomm3` extra.
- EtherCAT read-only PDO/SDO via an optional `pysoem` extra.
- OPC-UA certificate security + real Alarms & Conditions subscriptions.
- Sparkplug B protobuf decode bundled; MTConnect streaming long-poll.

**Missing a protocol, device, or feature? 缺功能提 issue/PR 欢迎留言** — open a [GitHub issue or PR](https://github.com/AIops-tools/OT-AIops/issues).

## License

MIT © wei