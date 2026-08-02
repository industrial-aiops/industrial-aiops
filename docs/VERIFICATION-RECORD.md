# 验证记录 — what has actually been run, per protocol

> **This file records evidence, not intent.** Every row says what was executed, by
> which test, at which rung of the ladder in
> [`PREVIEW-VERIFICATION.md`](PREVIEW-VERIFICATION.md) — and what was **not**.
> If a claim here cannot be reproduced by running the named test, the claim is wrong
> and should be deleted rather than softened.
>
> Last updated **2026-08-02** (third pass: four independent reviews of the day's
> work found three more product defects — an RCA pre-incident window diluted to
> its oldest samples on any historian with many tags, an IoTDB header whose
> unrecognised column names failed silently, and a malformed `endpoint_url` that
> still leaked a thread — plus a CI gate that checked container banners instead
> of the ports the tests actually connect to, and two rung labels that claimed
> more than they had. All fixed; see the 0.21.1 CHANGELOG entry.)
>
> Previously updated **2026-08-02** (second pass the same day: the two historian TSDBs
> went from rung 1 to 2a, which cost two product fixes — see note ⁶ —
> **PROFINET-DCP went from mock-only to 2b** on a veth pair, which cost a
> documentation fix — see note ⁷ — **EtherNet/IP's PCCC and Micro800 routes joined
> its Logix route at 2b**, **the MCP network transports and MTConnect `/assets`
> joined the live set**, **OPC-UA met a third-party stack for the first time** and
> cost two thread-leak fixes plus a documented interop wall — see note ⁸ — and the
> NATS live tests now have a broker on every CI build instead of skipping). The
> follow-up register at the bottom is the durable list of what is still worth
> testing, what is not, and the open questions — it is there rather than in a chat
> log so it survives the session that produced it.
>
> Previously updated 2026-08-01, after a code review of the day's changes found a
> harness bug that made this file's S7 row overstate (WORD reads returned silently
> wrong data), a test whose docstring described a wire path that never runs, and a
> protocol classified one rung too high. All three are corrected below and the
> corrections are visible rather than quietly folded in.

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
| **OPC-UA** | **2a**⁸ | `test_opcua_discovery.py`, `test_opcua_server.py`, `test_opcua_alarm_events.py`, `test_opcua_security.py`, `test_opcua_thirdparty_live.py`, `test_opcua_cert_trust_live.py` + `scripts/opcua_cert_harness.sh` | Real `asyncua` server: browse/discovery, tag model, alarm events, security-policy surface. Against **Microsoft opc-plc** (OPC Foundation .NET stack — an independent implementation): endpoint discovery, a real session, browse of the SERVER's own address space, typed reads with its status codes and timestamps, and its own `BadNodeIdUnknown`. **Certificate trust enforced both ways** on a second, strict server: an unknown client certificate is refused (and filed under `pki/rejected`), promoting it opens the encrypted Basic256Sha256 session, and a certificate whose SAN URI does not match the client's ApplicationUri stays refused even once trusted | A real vendor server (Siemens/Kepware/…) and its address-space quirks; a real PKI with a CA and CRLs; GDS / push provisioning |
| **Modbus TCP** | 2a | `test_modbus_tcp_live.py` | Real `pymodbus` `ModbusTcpServer` over loopback: FC03/FC04/FC01/FC02, float32 decode, non-zero start address, `apply_template` picking the declared register file (both banks exercised), `health_summary`'s per-address session, out-of-range → teaching error | Physical Modbus-TCP device; RTU-over-TCP gateways |
| **Modbus RTU** | 2a | `test_modbus_rtu_live.py` | Real `pymodbus` `ModbusSerialServer` over a socat PTY pair — actual RTU/CRC framing, all four function codes, float32 | Physical RS-485 bus / USB adapter; multi-drop addressing; baud/parity mismatch behaviour |
| **MQTT / Sparkplug B** | 2a | `test_uns_live_integration.py`, `test_mqtt_retained_undo.py` | Real **mosquitto** broker through the full paho loop: UNS audit, Sparkplug schema from NBIRTH, retained-publish BEFORE capture and inverse round-trip | Production EoN node / Sparkplug host application; broker auth/TLS |
| **BACnet/IP** | 2a | `test_bacnet_live.py` + `scripts/bacnet_live_harness.sh` | Real `bacpypes3` virtual device, **two IPs on one subnet**, real UDP broadcast Who-Is/I-Am round-trip; **the write path** — dry-run verified by reading back, BEFORE capture checked against what the device held, and the read-back `after`/`verified` reporting | Physical HVAC/BMS controller; COV subscription; trend logs; **whether a real controller accepts the write** — this virtual device does not, which is how the unverified `applied: true` was found (note ⁵) |
| **MTConnect** | **2b**¹ | `test_mtconnect_live.py` | Real HTTP agent: URL from host/port, `/sample?from=&count=` query, streamed body, **DTD/XXE guard on the first chunk** (discriminated from the full-body guard), size cap while reading, long-poll cursor advance + `instance_changed` stop, **`/assets` fetched and parsed** | Real machine-tool agent (Mazak/Okuma/…); MTConnect ≥2.0 schema |
| **SECS/GEM** | 2a⁴ | `test_secsgem_live.py` + `secsgem_equipment_harness.py` | Real `GemEquipmentHandler` in HSMS PASSIVE, our real `GemHostHandler` ACTIVE: S1F1/F2, S1F11/F12, S1F3/F4, S2F29/F30, S2F13/F14, S5F5/F6, and an **unsupported S7F19 teaching instead of returning raw bytes** | Real fab equipment; S7 process-program transfer; collection events / alarms in motion; **repeated short-lived sessions** (see note ²) |
| **Mitsubishi MC** | **2b** | `test_mc_live.py` + `mc_plc_harness.py` | Real `pymcprotocol` `Type3E` client vs **our** SLMP-3E server: CPU identity, batch word/bit read, signed-word decode, offsets, random read of words+dwords, write BEFORE capture verified by read-back | Physical MELSEC CPU; 1E/4E frames; ASCII mode; iQ-R addressing |
| **S7comm** | **2b** | `test_s7_live.py` + `s7_plc_harness.py` | Real `pyS7` client vs **our** ISO-TSAP server: COTP connect, PDU negotiation, DB/merker reads, signed INT, big-endian REAL, **WORD/DWORD/DINT/LREAL widths**, offsets, write BEFORE capture verified by read-back | Physical S7 CPU; PUT/GET access control; optimized-DB blocks; STRING/WSTRING; **our own bit handling** (see note ³) |
| **EtherNet/IP** | **2b** | `test_eip_live.py`, `test_eip_pccc_live.py` + `eip_plc_harness.py` + `eip_pccc_plc.py` | Real `pycomm3` vs **our** CIP PLC, on all three driver routes. **Logix** (`LogixDriver`): RegisterSession, ListIdentity, Forward Open, connected messaging, tag-list upload, single + Multiple-Service-Packet reads, write BEFORE capture verified by read-back. **PCCC/`slc`** (`SLCDriver`, CIP service 0x4B carrying DF1): processor-type diagnostic, the File-0 directory sequence behind `eip_list_tags`, typed reads of N/F/B/T elements, a masked bit write that leaves its neighbour alone, and **a device-side refusal of a bad address**. **Micro800**: pycomm3's own catalog-number detection, asserted by the batching that does NOT happen on the wire | Physical ControlLogix/CompactLogix/SLC-5-05/MicroLogix/Micro8xx; UDT/structured tags; program-scoped tags; PLC-5 addressing; ST/A files; a PCCC route bridged through a ControlLogix backplane |
| **Omron FINS** | **2c** | `test_fins.py` | Real UDP/TCP sockets — but the client is **in-repo** (stdlib) *and* the server is ours, so no independent implementation is involved | Physical Omron CPU; everything about the wire format is our reading of it |
| **HART-IP** | 1 + **2c** | `test_hart.py` | Command codec against the third-party `hart_protocol` (rung 1); the HART-IP UDP/TCP **transport is in-tree** and exercised against our own socket server (rung 2c) | Physical HART-IP gateway / multiplexer; burst mode against real devices |
| **IO-Link** | **2c** | `test_iolink.py` | Real HTTP against our mock master — **the vendor JSON API shape is our assumption** | Any real IO-Link master (ifm/Balluff/…); JSON schema drift |
| **PROFINET-DCP** | **2b**⁷ | `test_profinet_live.py` + `profinet_dcp_station.py` + `scripts/profinet_dcp_harness.sh` | Real `pnio-dcp` over a **veth pair** — raw layer-2 frames, ether-type 0x8892: IdentifyAll discovery (MAC read off the reply's Ethernet header), identify-by-name hit and miss, a **unicast DCP Get** (proven by what the station received, not by the answer), the governed **DCP Set** applied and reversed via the captured BEFORE, and the dry run proven to put no Set on the wire | A real ERTEC/Siemens station; RT cyclic data (out of scope); Blink / factory reset (out of scope); a real segment's timing and vendor quirks |
| **EtherCAT** | mock only | `test_ethercat.py` | Nothing on a wire | **Everything.** Structurally untestable without hardware — no software simulator exists |
| **BAS (Metasys/Niagara)** | mock only | `test_bas_tools.py` | Vendor REST mocked | Real supervisory controller; vendor API drift |
| **Ignition gateway** | mock only | `test_ignition_tools.py` | Vendor REST mocked | Real Ignition gateway; API version drift |

¹ **Corrected from 2a after review.** The first version of this file argued that
because the transport is HTTP + stdlib XML rather than a bespoke binary frame, the
"wrong together" risk did not apply. That argument does not hold: the *content* —
the Streams/Devices documents and the `nextSequence` / `instanceId` header
semantics — is hand-written by the same person who wrote the expectations, which is
exactly the 2b condition. The transport being third-party rescues the framing, not
the protocol semantics.

² **Repeated short-lived HSMS sessions are not proven.** `GemEquipmentHandler` does
not reliably return to `NOT_COMMUNICATING` between connects, so the test gives each
case its own equipment process. Whether real fab equipment behaves the same is
`待核实` — HSMS's T7 timer exists for that reason, so it is plausible; it is equally
plausible this is specific to secsgem. **Nothing is asserted either way.**

⁴ **SECS/GEM's 2a is real but narrower than it looks.** Host and equipment both come
from `secsgem`, so a misreading *inside that library* would satisfy both ends. The
rung holds for our connector code — an independent implementation of the GEM state
machine judges it — but not for the SECS-II codec layer beneath.

⁵ **BACnet's two-IP harness also runs off CI, which was previously written off.**
A privileged Linux container is enough — it adds the second address to its own
`eth0`, so no host networking is involved and no second machine is needed
(verified 2026-08-02 on macOS/arm64, where the earlier attempt against the host's
network had failed and been blamed on "the VM's bridge"). The same shape works
for PROFINET's veth pair and for the TDengine and energy protocol stacks, which
means every non-hardware row in this file can be reproduced on a developer
machine, not only on a runner.

**The BACnet write's `applied: true` was an unverified claim, found by this test.**
BAC0's `write()` returns `None` and raises nothing whether the device honoured the
request or silently dropped it. The connector now reads back and reports
(`after` / `verified`) rather than asserting success, and deliberately does **not**
judge a mismatch as failure — on a commandable object a higher priority legitimately
holds the value, and only the operator knows the priority scheme.

⁸ **This row was "sessions are impossible" for one day, and the fix was a pin.**
asyncua 1.x sent a `ServerUri` in CreateSession that OPC UA Part 4 §5.6.2 says is
set only when the endpoint has a `gatewayServerUri`; the .NET stack enforces it
with `BadServerUriInvalid`, so browse/read/subscribe could not run at all. asyncua
2.x makes the field opt-in, and the package moved to `asyncua>=2.0,<3` on
2026-08-02 — **64 existing OPC-UA tests passed unchanged**, so the migration was
the pin plus the version strings the skills quote.

Two things only a vendor stack could teach, both now pinned by tests:

- **Certificate trust is enforced, and the connector's `certificate` verdict is
  the one that gets produced.** The in-process `asyncua` server runs a permissive
  validator that accepts any client certificate, so that whole verdict class had
  never been produced by something that enforces it.
- **A trusted certificate is still refused if its SAN URI does not match the
  ApplicationUri the client announces** (`BadCertificateUriInvalid`). `asyncua`'s
  server does not check this, so a certificate minted against an in-house test
  server can be trusted by a vendor server and still fail — a site-visit-shaped
  surprise, now a test.

Harness caveat worth keeping: the promotion into the trusted store must be
performed **inside the server's own filesystem**. The identical file written from
the host across a macOS bind mount leaves the session refused (measured, 30s+),
while `docker exec` copying it is honoured on the next connect.

Pointing at that server also surfaced **two thread leaks** in the diagnostics
path, both of which hung the process rather than failing: the failed-connect
branch returned its verdict without disconnecting, and `_build_opcua_client`
abandoned an already-constructed client if anything after asyncua's constructor
raised (a locked secret store, a bad security string). `asyncua.sync.Client`
starts a **non-daemon** thread loop in that constructor, so `iaiops doctor` never
returned to the prompt and an MCP server accumulated one thread per failed
diagnosis. Both are fixed and pinned by a subprocess test — mocked
clients cannot see this, because a fake `disconnect()` is a no-op either way.

⁷ **PROFINET stopped being mock-only without any new hardware — and the move
found a documentation defect.** A veth pair plus a raw-socket responder was all it
took; the earlier note that lumped this with EtherCAT was wrong because DCP is
request-response over Ethernet, so the missing half was a *responder*, not a
device. What the round-trip showed: `pnio_dcp.Device` (1.2.0) exposes only
name_of_station / MAC / IP / netmask / gateway / family, so **`vendor_id`,
`device_id` and `device_roles` are always empty** — the station sends DeviceID and
DeviceRole blocks and the client drops them. `profinet_asset_inventory`'s
`io_controller_count` is therefore structurally 0, which the tool documentation had
promised otherwise. The mocked tests could not see it: their fake device had the
attributes invented for it. The connector and tool docs now say so, and the live
test asserts the emptiness so a future pnio-dcp that fixes it turns red.

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

## The MCP interface itself

| Area | Rung | Test | What actually runs | Not covered |
|---|---|---|---|---|
| **MCP over stdio** | 2a⁹ | `test_mcp_stdio_live.py` | The SDK's own `stdio_client` + `ClientSession` against the real `mcp_server.server:main` entrypoint as a subprocess: initialize handshake, `list_tools()`, a JSON-RPC tool call, a connector failure arriving as readable content rather than a session-killing protocol error, **the `ToolAnnotations` a client receives**, **what `IAIOPS_NO_EGRESS=1` withholds as seen from outside**, and `IAIOPS_MCP` profile selection | Any client other than the reference SDK; Claude Desktop / IDE hosts; TLS termination and an authenticating gateway in front of the HTTP transports |
| **MCP over HTTP/SSE** | 2a⁹ | `test_mcp_http_live.py` | The SDK's `streamablehttp_client` and `sse_client` against the real entrypoint run as a subprocess under uvicorn: initialize, `list_tools()`, a tool call whose connector failure arrives as content, and **the IP-allowlist middleware 403ing a client outside `IAIOPS_ALLOWLIST_IPS`** — a control that exists on no other transport — with an unconfigured server proving it is off by default | TLS; a real gateway in front; clients other than the reference SDK |

⁹ **Both MCP rows carry the SECS/GEM caveat (note ⁴), and for the same reason.**
The server under test is ours, and the frames on both sides are produced by ONE
third-party library — `FastMCP` from the `mcp` SDK on the server, the same SDK's
client in the test. That earns 2a for *our* code (the SDK's own client parses
what our server emits, and a wrong tool schema or a broken profile gate shows up
immediately), but a misreading INSIDE the SDK would satisfy both ends. A second
implementation of MCP — a different client, or Claude Desktop — is what would
close that, and neither has been run against this server.

Until 2026-08-01 nothing drove this at all — every test called tool functions
in-process, so the product's **primary interface** was unexercised. Two of the
assertions above had previously been checked against our own registry, which is not
where a client looks. The network transports followed on 2026-08-02: they are what
`deploy/margo` and the IGEL submission actually expose, and the allowlist middleware
had never answered a request from a client that was not on the list.

## Egress — the paths that ship data off-box

| Sink | Rung | Test | What actually runs | Not covered |
|---|---|---|---|---|
| **NATS** | 2a | `test_egress_live.py` | A **real NATS broker**; published messages are read back off it by a real subscriber (subjects and payloads), plus a bounded-failure assertion against an unreachable broker. Runs on every CI build since 2026-08-02 — before that the gate started no broker, so this row was true of local runs only | Auth/TLS; JetStream; a real plant bus under load |
| **InfluxDB** | 2b | `test_egress_live.py` | A real HTTP endpoint recording exactly what the sink emits: measurement, value, bucket/org query, `Authorization` header, and that five points become **one** request | A real InfluxDB server accepting the line protocol; v1 vs v2 differences beyond the endpoint shape |
| **IoTDB** | **2a**⁶ | `test_tsdb_live.py` | A real **apache/iotdb 1.3.2**: sink write → reader read-back, time-bound and tag filters applied server-side, the `LAST` and aggregate result shapes parsed, non-numeric points skipped, endpoint filter refused | A vendor/clustered IoTDB; schema templates; IoTDB 2.x |
| **TDengine** | **2a**⁶ | `test_tsdb_live.py` | A real **taosd 3.3.5**: the `value` reserved-word DDL, auto-sub-table INSERT…USING…TAGS, reader query/latest/coverage, time bounds applied server-side | A physical/clustered taosd; the REST + WebSocket connectors; retention/keep policies |
| **SQLite / Parquet** | local | `test_sink_sqlite_local.py`, `test_export.py` | Real local files — no network counterparty exists to be wrong about | — |

⁶ **Both TSDBs moved from rung 1 to 2a on 2026-08-02, and the move cost two
product fixes** — which is the argument for making it, since "the client library
has the method we call" had been standing in for "the database answers us".

- **The IoTDB reader attributed one tag's value to another tag.** A wildcard
  `SELECT value FROM root.db.*` declares one column per series, and the reader
  zipped that header against each record's fields. A real IoTDB 1.3.2 returns the
  fields **compacted** under a `WHERE` clause — so a time-bounded query, i.e. the
  RCA path this reader exists for, returned the right numbers under the wrong
  names. Now `ALIGN BY DEVICE`, where every row carries its own device label.
- **The TDengine coverage query could never have run.** `MIN(ts)` / `MAX(ts)` on a
  TIMESTAMP column is rejected by taosd 3.x (`[0x2802]: Invalid parameter data
  type : min`), so `historian_coverage` against TDengine raised for every caller.
  Now `FIRST(ts)` / `LAST(ts)`.

Both had passing unit tests. The mocks had been written to match the parser, so
they agreed with it; the fakes now reproduce the shapes the servers actually
returned, recorded from the live runs.

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

## Still testable — the follow-up register

Kept here rather than in a chat log so it survives. Ordered by what a reader should
pick up first. Everything above the line is *doable*; everything below it is not, and
saying so is the point.

### Doable, not done

**Every item this list opened with was cleared on 2026-08-02** (they are compressed
below). What follows is what those six left behind — smaller, but named here for the
same reason: so nobody has to reconstruct it.

1. ~~**Migrate to `asyncua` 2.x**~~ **Done 2026-08-02** — `asyncua>=2.0,<3`; the 64
   existing OPC-UA tests passed unchanged, and `test_opcua_thirdparty_live.py` was
   rewritten from "sessions are impossible" to the reads themselves (note ⁸).
2. **TDengine's HTTP / WebSocket connectors** (`taosrest`, `taos-ws-py`). The native
   `libtaos` client is a vendor tarball fetched from a CDN in CI; the other connectors
   would remove that dependency, and each is a different wire format from the one
   `test_tsdb_live.py` covers today.
3. ~~**Certificate-trust enforcement**~~ **Done 2026-08-02** — both directions against a
   strict opc-plc (`test_opcua_cert_trust_live.py`), including the SAN-URI rule in
   note ⁸. What is left of this entry: a **real PKI** — a CA-issued certificate, an
   issuer chain and a CRL, rather than self-signed peers — and GDS/push provisioning.
4. **EtherNet/IP breadth on the routes that now exist**: UDT / structured tags,
   program-scoped tags, PLC-5 addressing, ST/A files, and a PCCC route bridged through
   a ControlLogix backplane.
5. **MTConnect ≥2.0 schema** — the live agent speaks 1.7.
6. ~~**Truncation keeps the OLDEST samples, everywhere.**~~ **Done 2026-08-02** —
   `SampleFilter.newest_first` is pushed into all three readers' `ORDER BY` (not
   faked by reversing in Python; the live tests assert *which* samples came back),
   and the RCA pre-incident window sets it. Rows still return oldest→newest, so no
   caller changed. Default stays oldest-first for the general query API.
7. **A second MCP implementation.** Both MCP rows are 2a with note ⁹: the client
   and the server come from the same SDK. Driving the server from a different
   client — or from Claude Desktop — is what would close that.

### Cleared on 2026-08-02

Kept as one line each, because "this was tested and here is where" is the part worth
carrying; the notes above hold the detail and the defects each one found.

- **PROFINET-DCP** mock-only → **2b** on a veth pair (note ⁷).
- **EtherNet/IP PCCC + Micro800** mock-only → **2b** (`test_eip_pccc_live.py`), which
  also closed this connector's "wire-level error never reached" gap.
- **IoTDB + TDengine** rung 1 → **2a** (note ⁶) — two reader defects fixed.
- **MTConnect `/assets`** — now part of the live-agent round-trip.
- **The MCP HTTP/SSE transports** → **2a**, including the IP allowlist (TLS and a real
  gateway in front stay out of scope by HLD decision **D7**).
- **OPC-UA vs a third-party stack** — answered, and the answer was no (note ⁸); two
  thread leaks fixed on the way.

### Not doable, and why

- **EtherCAT.** `pysoem`/SOEM drives a real NIC with distributed-clock cyclic exchange
  against real slaves. **No software simulator exists.** Do not keep proposing live
  tests for it. (PROFINET was in this list once — see note ⁷ for why it did not
  belong. The difference is real: DCP is request-response, so a responder suffices;
  EtherCAT is a cyclic frame passed slave-to-slave in hardware, and a responder is
  not what is missing.)
- **2c → 2a for FINS, HART-IP's transport, and IO-Link.** There is no third-party
  counterpart to test against; only real gear (rung 3) can lift them.
- **BAS (Metasys/Niagara) and Ignition.** Vendor REST APIs — only a real supervisory
  controller or gateway moves them.
- **Rung 3, everywhere.** Hardware-gated by definition. See
  [issue #28](https://github.com/industrial-aiops/industrial-aiops/issues/28).

### Open questions carried forward

- **Does real fab equipment reconnect the way secsgem does?** Repeated short-lived HSMS
  sessions fail against `GemEquipmentHandler`; HSMS's T7 timer makes it plausible for
  real tools, and equally plausible that it is specific to secsgem. **Not asserted
  either way** — the harness sidesteps it with a process per test.
- **Does a real BACnet controller accept `bacnet_write_property`?** The virtual device
  does not, at any priority. Untested in both directions.
- **`bacpypes3` and `secsgem` both keep module-level state** that makes a second
  device/handler in one interpreter unreliable. Worked around (one session sequence,
  one process); not diagnosed upstream.

