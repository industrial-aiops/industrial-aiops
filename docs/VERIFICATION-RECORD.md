# 验证记录 — what has actually been run, per protocol

> **This file records evidence, not intent.** Every row says what was executed, by
> which test, at which rung of the ladder in
> [`PREVIEW-VERIFICATION.md`](PREVIEW-VERIFICATION.md) — and what was **not**.
> If a claim here cannot be reproduced by running the named test, the claim is wrong
> and should be deleted rather than softened.
>
> Last updated **2026-08-01**.

## The rungs, in one line each

| rung | meaning | who judges our frames |
|---|---|---|
| **1** | codec / API surface against the real library | the library's own symbols |
| **2a** | real wire to a **third-party** server | somebody else's implementation of the spec |
| **2b** | real wire to a server **we wrote** from the spec | the third-party *client* parses our frames |
| **2c** | real wire, but **both ends are ours** | nobody independent |
| **3** | real physical / vendor-virtual device | the device |

**2b ≠ 2a, 2c ≠ 2b, and no amount of any of them adds up to 3.** Rung 3 is **zero
for every protocol in both repos.** Nothing below changes that.

## Base package (`iaiops`)

| Protocol | Rung | Test | What actually runs | Not covered |
|---|---|---|---|---|
| **OPC-UA** | 2a | `test_opcua_discovery.py`, `test_opcua_server.py`, `test_opcua_alarm_events.py`, `test_opcua_security.py` | Real `asyncua` server: browse/discovery, tag model, alarm events, security policy surface | Real vendor OPC-UA server (Siemens/Kepware/…); certificate trust against real PKI |
| **Modbus TCP** | 2a | `test_modbus_tcp_live.py` | Real `pymodbus` `ModbusTcpServer` over loopback: FC03/FC04/FC01/FC02, float32 decode, non-zero start address, `apply_template` picking the declared register file (both banks exercised), `health_summary`'s per-address session, out-of-range → teaching error | Physical Modbus-TCP device; RTU-over-TCP gateways |
| **Modbus RTU** | 2a | `test_modbus_rtu_live.py` | Real `pymodbus` `ModbusSerialServer` over a socat PTY pair — actual RTU/CRC framing, all four function codes, float32 | Physical RS-485 bus / USB adapter; multi-drop addressing; baud/parity mismatch behaviour |
| **MQTT / Sparkplug B** | 2a | `test_uns_live_integration.py`, `test_mqtt_retained_undo.py` | Real **mosquitto** broker through the full paho loop: UNS audit, Sparkplug schema from NBIRTH, retained-publish BEFORE capture and inverse round-trip | Production EoN node / Sparkplug host application; broker auth/TLS |
| **BACnet/IP** | 2a | `test_bacnet_live.py` + `scripts/bacnet_live_harness.sh` | Real `bacpypes3` virtual device, **two IPs on one subnet**, real UDP broadcast Who-Is/I-Am round-trip | Physical HVAC/BMS controller; write, COV subscription, trend logs |
| **MTConnect** | 2a¹ | `test_mtconnect_live.py` | Real HTTP agent: URL from host/port, `/sample?from=&count=` query, streamed body, **DTD/XXE guard on the first chunk** (discriminated from the full-body guard), size cap while reading, long-poll cursor advance + `instance_changed` stop | Real machine-tool agent (Mazak/Okuma/…); Assets; MTConnect ≥2.0 schema |
| **SECS/GEM** | 2a | `test_secsgem_live.py` + `secsgem_equipment_harness.py` | Real `GemEquipmentHandler` in HSMS PASSIVE, our real `GemHostHandler` ACTIVE: S1F1/F2, S1F11/F12, S1F3/F4, S2F29/F30, S2F13/F14, S5F5/F6, and an **unsupported S7F19 teaching instead of returning raw bytes** | Real fab equipment; S7 process-program transfer; collection events / alarms in motion; **repeated short-lived sessions** (see note ²) |
| **Mitsubishi MC** | **2b** | `test_mc_live.py` + `mc_plc_harness.py` | Real `pymcprotocol` `Type3E` client vs **our** SLMP-3E server: CPU identity, batch word/bit read, signed-word decode, offsets, random read of words+dwords, write BEFORE capture verified by read-back | Physical MELSEC CPU; 1E/4E frames; ASCII mode; iQ-R addressing |
| **S7comm** | **2b** | `test_s7_live.py` + `s7_plc_harness.py` | Real `pyS7` client vs **our** ISO-TSAP server: COTP connect, PDU negotiation, DB/merker reads, signed INT, big-endian REAL, offsets, write BEFORE capture verified by read-back | Physical S7 CPU; PUT/GET access control; optimized-DB blocks; **our own bit handling** (see note ³) |
| **EtherNet/IP** | **2b** | `test_eip_live.py` + `eip_plc_harness.py` | Real `pycomm3` `LogixDriver` vs **our** CIP PLC: RegisterSession, ListIdentity, Forward Open, connected messaging, tag-list upload, single + Multiple-Service-Packet reads, write BEFORE capture verified by read-back | Physical ControlLogix/CompactLogix; **PCCC (`slc`) and Micro800 paths — mock only**; UDT/structured tags; program-scoped tags |
| **Omron FINS** | **2c** | `test_fins.py` | Real UDP/TCP sockets — but the client is **in-repo** (stdlib) *and* the server is ours, so no independent implementation is involved | Physical Omron CPU; everything about the wire format is our reading of it |
| **HART-IP** | 1 + **2c** | `test_hart.py` | Command codec against the third-party `hart_protocol` (rung 1); the HART-IP UDP/TCP **transport is in-tree** and exercised against our own socket server (rung 2c) | Physical HART-IP gateway / multiplexer; burst mode against real devices |
| **IO-Link** | **2c** | `test_iolink.py` | Real HTTP against our mock master — **the vendor JSON API shape is our assumption** | Any real IO-Link master (ifm/Balluff/…); JSON schema drift |
| **PROFINET-DCP** | mock only | `test_profinet.py` | Nothing on a wire | **Everything.** See "still testable" below — this one is *not* hopeless |
| **EtherCAT** | mock only | `test_ethercat.py` | Nothing on a wire | **Everything.** Structurally untestable without hardware — no software simulator exists |
| **BAS (Metasys/Niagara)** | mock only | `test_bas_tools.py` | Vendor REST mocked | Real supervisory controller; vendor API drift |
| **Ignition gateway** | mock only | `test_ignition_tools.py` | Vendor REST mocked | Real Ignition gateway; API version drift |

¹ MTConnect's agent is an HTTP server we wrote, but the protocol under test is
**HTTP + XML parsed by stdlib/`requests`**, not a bespoke binary frame — the
"could we both be wrong together" risk that defines 2b does not really apply. Rung
2a is the honest call; a reader who disagrees can read it as 2b without any claim
here changing.

² **Repeated short-lived HSMS sessions are not proven.** `GemEquipmentHandler` does
not reliably return to `NOT_COMMUNICATING` between connects, so the test gives each
case its own equipment process. Whether real fab equipment behaves the same is
`待核实` — HSMS's T7 timer exists for that reason, so it is plausible; it is equally
plausible this is specific to secsgem. **Nothing is asserted either way.**

³ **The S7 bit test does not cover our bit handling.** Mutation testing showed pyS7
*coalesces* neighbouring bit tags into one byte read and extracts the bits itself.
The test pins the connector's address construction plus pyS7's extraction; the
harness's single-bit branch is dead on that path and says so.

## Energy package (`iaiops-energy`)

| Protocol | Rung | Test | What actually runs | Not covered |
|---|---|---|---|---|
| **IEC 60870-5-104** | 2a | `test_iec104_live.py` | Real `c104` client↔server: general interrogation returns seeded points with quality, bad IOA → `found=False` with **no fabricated value**, server-side capture proves **no control ASDU** is ever issued | Physical RTU; control direction (deliberately absent) |
| **DNP3 / IEEE 1815** | 2a | `test_dnp3_live.py` + `scripts/build_pydnp3.sh` | Real **opendnp3** outstation: `is_online()` reflects the real channel state, integrity poll returns the seeded binary/analog/counter database by class | Physical RTU; control direction (deliberately absent) |
| **IEC 61850 MMS** | 2a | `test_iec61850_live.py` | Real **libiec61850** MMS server over ISO-on-TCP: logical-device browse, seeded measurand read, bad reference → MMS data-access error rather than a fabricated value | Physical IED; GOOSE / SV (out of scope) |

All three run on **every CI build**, and a skipped live test **fails** the build.

## Cross-cutting (not protocol-specific)

| Area | Test | What it pins |
|---|---|---|
| Governance harness present | `test_server_governance.py` | Every registered tool carries `@governed_tool`; server refuses to start otherwise |
| Approval / MOC gate | `test_write_approval_contract.py` | All ten high-risk writes: denied without an approver **and the connector never reached**; runs with one; preview needs none. Mutation-verified |
| Credential redaction | `test_credential_redaction_contract.py` | No tool or CLI command audits a credential in the clear, both front-ends, plus runtime proof |
| Audit fidelity | `test_audit_status_fidelity.py` | A returned `{error, hint}` is recorded as an error, not `ok`; the circuit breaker is told the truth |
| Runaway / budget | `test_denied_retry_loop.py`, `test_budget.py` | A retried denial is eventually stopped; denials still cost nothing against the ceilings |
| Undo coverage | `test_smoke.py` | All ten high-risk writes declare an undo — no exemptions |
| Audit hash chain | `test_audit_integrity.py` | Tamper detection over the chain |
| Library binding contracts | `test_binding_contracts.py` | BAC0, IoTDB `Session`, taospy against **real libtaos** — the assumptions our sinks make |

## Still testable (honest)

**One candidate remains, and it is not EtherCAT.**

- **PROFINET-DCP — plausible, not attempted.** `pnio-dcp` binds an L2 raw socket to a
  local interface and broadcasts DCP Identify. On Linux with `CAP_NET_RAW`, a **veth
  pair** plus a raw-socket responder on the peer could answer with DCP Identify-Ok
  frames, which would make this a genuine **2b** (pnio-dcp's own parser judging our
  frames). It needs root, so it cannot run in the ordinary gate job, but the Linux box
  at `192.168.60.236` can do it. Earlier notes lumped this with EtherCAT as
  "impossible"; that was too quick, and this row exists so the mistake is not repeated.
- **EtherCAT — structurally untestable.** `pysoem`/SOEM drives a real NIC with
  distributed-clock cyclic exchange against real slaves. There is no software
  simulator. Do not keep proposing live tests for it.
- **2c → 2a is not reachable by more work here.** FINS, HART-IP's transport and
  IO-Link have no third-party counterpart to test against; only real gear (rung 3)
  can lift them.
- **BAS / Ignition** are vendor REST APIs; only a real supervisory controller or
  gateway moves them.
