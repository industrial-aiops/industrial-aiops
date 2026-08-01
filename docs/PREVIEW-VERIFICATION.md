# 预览协议真机在环验证 — runbook (待核实 → verified)

> **This task is hardware-gated and cannot be completed in CI.** Several protocols
> ship as **preview (`待核实`)** because they need real gear (a live outstation /
> IED / HVAC controller / serial bus) that no CI runner has. This runbook is the
> repeatable procedure to promote each one to **verified** once the gear is on the
> bench — it does **not** mark anything verified that hasn't actually been run.
> It mirrors the 2026-06-30 energy/building binding pass.

## What "verified" means here (honest ladder)

1. **codec / surface verified** — the driver's symbols + our encode/decode run
   against the real library (already true for most; done in CI).
2. **loopback / in-process verified** — a real wire to a server on localhost. This
   splits in two, and the difference is not cosmetic:
   - **2a — third-party counterparty.** The far end is somebody else's
     implementation of the spec: pymodbus, bacpypes3, mosquitto, opendnp3,
     libiec61850, `c104`, asyncua, secsgem's equipment. An independent
     implementation judges our frames, so a shared misreading is unlikely.
   - **2b — our own server.** The client library ships no server, so the far end is
     written by us from the frame layout (`tests/mc_plc_harness.py`,
     `s7_plc_harness.py`, `eip_plc_harness.py`). **If we misread the spec, harness
     and expectations are wrong together.** It is still far stronger than a mock —
     the real client parses every byte and rejects malformed frames, and the harness
     decodes the request so the wrong device/tag/offset returns different data — but
     it is *not* independent confirmation. Say "2b" when reporting it; do not let it
     be quoted as if it were 2a.
   - **2c — both ends ours.** A real socket, but the *client* is in-repo too, so no
     independent implementation is involved anywhere. Real bytes move; nobody
     checks our reading of the spec. Weakest rung that still involves a wire.
3. **live-gear verified** ← *this runbook* — real physical/virtual device on the
   bench, read end-to-end through the connector.

Only (3) flips the README banner from `待核实` to verified. **2b ≠ 2a, 2c ≠ 2b, and
no amount of any of them adds up to 3.**

**Current standing (2026-08-01)** — the per-protocol evidence, including what each
test does *not* cover, is in [`VERIFICATION-RECORD.md`](VERIFICATION-RECORD.md):

- **2a:** OPC-UA · Modbus-TCP · Modbus-RTU · MQTT/Sparkplug · BACnet · SECS/GEM ·
  IEC-104 · DNP3 · IEC-61850
- **2b:** MTConnect · Mitsubishi MC · S7comm · EtherNet/IP
- **2c:** Omron FINS · HART-IP (transport; its codec is rung 1 against
  `hart_protocol`) · IO-Link
- **mock only:** PROFINET-DCP · EtherCAT · BAS · Ignition

**Level 3 is zero for every protocol in both repos.**

Two classifications that a review corrected, kept visible because the correction is
the useful part:

- **MTConnect was listed 2a and is 2b.** Its HTTP *transport* is third-party, but
  the MTConnect *content* — the Streams/Devices XML, the `nextSequence` /
  `instanceId` header semantics — is hand-written by whoever also wrote the
  expectations. That is precisely the "wrong together" condition 2b names. The
  transport being stdlib does not rescue it.
- **SECS/GEM's 2a is real but narrower than it looks.** Host and equipment both come
  from `secsgem`, so a misreading *inside that library* would satisfy both ends. The
  rung holds for **our connector code** — an independent implementation of the GEM
  state machine judges it — but not for the SECS-II codec layer.

PROFINET-DCP is the one mock-only protocol that is *not* hopeless: `pnio-dcp` binds
an L2 raw socket, so a veth pair plus a raw-socket responder on Linux with
`CAP_NET_RAW` would make it a real 2b. EtherCAT is structurally untestable — SOEM
drives a real NIC against real slaves and no software simulator exists.

## Preview inventory (source of truth: `README.md` validation banner)

| Protocol | Gear needed | Why not in CI |
|----------|-------------|---------------|
| **DNP3** | live outstation (or hardware sim) | `pydnp3` no wheel; needs a real link |
| **IEC-61850** | live IED (substation relay) | MMS server + real dataset |
| ~~**BACnet/IP** (read)~~ | ~~live HVAC / BMS controller~~ | **read path verified 2026-07-02** (real bacpypes3 virtual device, two-IP subnet in a Linux container, `tests/test_bacnet_live.py`); live HVAC write/COV/trend still pending |
| **HART-IP** (wire) | live HART-IP gateway | only the codec is CI-verified |
| ~~**Modbus-RTU**~~ | ~~RS-485 / USB serial slave~~ | **verified 2026-07-02** (socat PTY + pymodbus RTU server, `tests/test_modbus_rtu_live.py`); physical RS-485 device still pending |
| **EtherCAT** | real EtherCAT bus + Linux root | no software simulator exists |
| **PLCnext vPLC** (live) | physical/virtual PLCnext | route-verified only (see below) |

## Per-protocol procedure

For each protocol, on a host with the gear reachable:

1. **Install** the extra: `pip install "iaiops[<proto>]"` (e.g. `iaiops[dnp3]`).
   EtherCAT additionally requires Linux + root + the NIC bound to the bus.
2. **Configure** a target in `~/.iaiops/config.yaml` (`protocol: <proto>`, host/port
   or serial params). See `iaiops/core/runtime/config.py` `TargetConfig` for fields.
3. **Probe the route:** `iaiops doctor` — expect a green ✓ for the target (OPC-UA
   failures auto-classify via `diagnose_connection`).
4. **Read end-to-end** with the connector's read op / CLI, e.g.:
   - DNP3: `iaiops dnp3 link-status` then `dnp3 integrity-poll`
   - IEC-61850: `iaiops iec61850 device-directory` → `iec61850 read`
   - BACnet: `iaiops bacnet discover` → `bacnet read-points`
   - HART-IP: `iaiops hart device-identity` → `hart primary-variable`
   - Modbus-RTU: `iaiops modbus read-holding` over `transport: rtu`
   - EtherCAT: `iaiops ethercat slaves` → read PDO/SDO
   - PLCnext: point `protocol: opcua` (opc.tcp 4840) **and** `protocol: modbus` at
     the vPLC; run `doctor` + `opcua discover-tags` on `Arp.Plc.Eclr`.
5. **Pass criteria:** real values returned with correct **dual timestamp + quality
   + source**; no silent interpolation; a deliberate fault (unplug / bad address)
   produces a *teaching* error, not a crash.
6. **Record evidence:** device model + firmware, library version, date, the command
   output. Attach to the PR that flips the status.

## Where to flip status when a protocol passes (keep all four in sync)

Per `CLAUDE.md`: 支持版本是一等公民 — update every surface in the same PR:

1. `iaiops/core/brain/overview.py` — edit that protocol's `requirements` field:
   drop `待核实`, note "live <device> verified <date>".
2. `README.md` (+ `README.zh-CN.md`) — move it from the `待核实` list to the verified
   sentence in the validation banner.
3. The internal HLD §8.2 (design doc, lives outside this repo — skip if unavailable):
   flip the row's 自测 column (`⚠️ → ✅ live <device>`).
4. `docs/ROADMAP.md` — tick the protocol's follow-up.
5. Add/lift a test: promote its contract test to an `@pytest.mark.integration` live
   test guarded by an env var (so CI skips, the bench runs it) — mirror
   `tests/test_opcua_server.py` (real server) and `tests/test_plcnext_route.py`.

## Quality gates (unchanged)

`pytest` + `ruff` + `bandit` (0 Medium+) green; every MCP tool `_is_governed_tool`;
zero cross-brand banned words; any live write path stays HIGH risk / dry-run + MOC.
Live verification never relaxes the read-first posture.

## Current status (2026-07-02)

**Modbus-RTU is now verified over a real serial link.** Because RTU is serial (not
socketable) it can be exercised WITHOUT physical hardware: `socat -d -d pty,raw,echo=0
pty,raw,echo=0` creates a connected pseudo-terminal pair (a software null-modem), a
`pymodbus` `ModbusSerialServer` (RTU framer) serves seeded registers on one PTY, and
the connector's `ModbusSerialClient` reads them back over the other via
`TargetConfig(transport="rtu", serial_port=...)`. `tests/test_modbus_rtu_live.py`
(integration-marked, skips when `socat`/`pyserial` are absent) asserts
holding/input/coil/discrete round-trips — real RTU framing, not a mocked client. Run
2026-07-02 in a `python:3.12-slim` container (5/5 passed). This sits above ladder
level 2 (real wire, in-process peer); a **physical RS-485 device** is still pending.

**The BACnet/IP read path is now verified against a real (virtual) device.** BACnet/IP
discovery is UDP broadcast, which loopback does not carry — so the device and the
connector must sit on two IPs of one real subnet (that is why an earlier macOS-host
attempt was blocked). In a Linux `python:3.12-slim` container with `NET_ADMIN`, a
second IP is added to `eth0` (`ip addr add 172.17.240.240/16 dev eth0`); a real
`bacpypes3` device (DeviceObject + NetworkPortObject + analog/binary Value objects)
binds the alias IP, and the **actual connector ops** run against it bound to the
primary IP. This surfaced (and fixed) the real bug: modern BAC0 (2024+) is async-first
(`BAC0.lite()` needs a running loop; `who_is`/`read`/`readRange` are coroutines), so
the connector now bridges BAC0 onto a dedicated event loop
(`iaiops/core/runtime/bacnet_async.py`), and `_norm_device`/`_norm_object` were fixed
to parse bacpypes3's real `IAmRequest` (`iAmDeviceIdentifier`/`pduSource`) and
kebab-case object types. `tests/test_bacnet_live.py` (integration-marked, gated on
`IAIOPS_BACNET_CLIENT_IP`+`IAIOPS_BACNET_DEVICE_IP`, skips otherwise) asserts a genuine
Who-Is discover + present-value read round-trip — passed 2026-07-02. Live BACnet
**write / COV / trend-log** on real HVAC gear stays pending (not exercised live).

**The energy edition (`iaiops-energy` repo) is now verified for its whole read path.**
Same container approach: **IEC-104** (real `c104` loopback — genuinely verified **2026-07-13**,
see the dated recipe below; the earlier "loopback verified" claim was an overclaim — no c104 test
existed until then), **DNP3** monitor
path (real `opendnp3` outstation — `pydnp3` built in-container with a pybind11 swap;
`tests/test_dnp3_live.py`), and **IEC-61850 MMS** monitor path (real in-process
`libiec61850` server via the `pyiec61850` wheel's server API; `tests/test_iec61850_live.py`).
Each surfaced and fixed genuine driver bugs (DNP3 SOE handler / GC lifetime; IEC-61850
SWIG return-shape decode / browse-by-level / access-error detection) — those drivers were
mock-only and non-functional against the real bindings before. Control/GOOSE/SV out of
scope; live RTU/IED reads remain the only pending step there.

**Remaining truly pending:** **EtherCAT** (no software simulator — hardware bus only) and
**physical-device** passes (RS-485 for Modbus-RTU, live HVAC for BACnet write/COV/trend,
live HART-IP gateway, live RTU/IED). This runbook is the standing procedure; nothing is
marked verified without a real round-trip. PLCnext is **route-verified** (in-process
asyncua + faked Modbus, `tests/test_plcnext_route.py`); its *live* row stays here.

## Current status (2026-07-13) — IEC-104 verified + reusable Docker recipe

**IEC-104 (`iaiops-energy`) is now genuinely `verified (monitor path)`** (0.1.5). The real
`c104` client↔server round-trip (`tests/test_iec104_live.py` + `tests/iec104_server_harness.py`)
passes in a Linux container: `iec104_connection_info` discovers the seeded station,
`iec104_interrogate` (C_IC) returns the seeded `M_ME_NC_1` + `M_SP_NA_1`, `iec104_read_point`
reads the measurand, a bad IOA → `found=False` with no fabricated value, and server-side ASDU
capture proves no control ASDU (C_SC/C_DC/C_SE) is issued. Physical RTU still `待核实`. It ran
green in a `python:3.11-slim` container and now runs on every push in the energy CI gate.

Getting there found (and fixed) a **real shipped bug**: the client-side `on_new_station` /
`on_new_point` discovery callbacks would fail against *any* real `c104` RTU — see the gotcha below.

### Recipe: verify a native-Python-binding preview protocol in Docker (no bench hardware)

When a preview protocol's binding ships **no wheel for the dev host** (macOS) but builds/installs
on Linux, a Linux container is a valid ladder-level-2 verifier (real wire, in-process peer) — the
same standard used for Modbus-RTU and BACnet above. Steps (IEC-104 / `c104` is the worked example):

1. **Container + toolchain.** `docker run --rm -v "$PWD":/work -w /work python:3.11-slim bash -c '…'`;
   the binding may be **sdist-only** (e.g. `c104` 2.x — no macOS wheel, and its sdist fails under
   Apple Clang but compiles fine with Linux gcc), so `apt-get install -y build-essential cmake git`
   first. (Some bindings have manylinux wheels — then no toolchain is needed.)
2. **Install EDITABLE:** `pip install -e ".[<extra>,dev]"`. **Editable is required**, not cosmetic:
   the live tests spawn a child process (native peer + client can't share one interpreter safely),
   and the child does `from tests.<harness> import …`; only an editable install puts the repo root
   on `sys.path` (via its `.pth`) so that import resolves. A non-editable `pip install .` makes the
   child fail with `ModuleNotFoundError: No module named 'tests'`.
3. **Run the integration test** (energy CI does **not** deselect `integration`, so a plain
   `pytest -q` runs it; or target it: `pytest -q -m integration tests/test_<proto>_live.py`).
4. **Gotcha — strict callback signatures.** Bindings like `c104` validate registered callbacks by
   their **real annotations**. Two traps: (a) modules using `from __future__ import annotations`
   **stringize** annotations → the binding sees `'Any'` not the real type and rejects it; (b) `Any`
   placeholders are wrong types. Fix: after `def cb(...)`, set the exact expected signature as real
   objects — `cb.__annotations__ = {"server": c104.Server, "data": bytes, "return": None}`. To learn
   the **exact** expected signature, register a deliberately-wrong callback and read the `ValueError`
   (it prints e.g. `expected: (client:c104.Client,connection:c104.Connection,common_address:int)->None`).
5. **Pass criteria** (as above): real values with quality/timestamp; a bad address → teaching error,
   no fabricated value; monitor-only paths issue no control frames (assert via server-side capture).
6. **Make CI run it durably:** install the extra **non-best-effort** in the CI gate, so the
   `@pytest.mark.integration` live test runs every push, and make a **skip fail the build** —
   a skipped live test is indistinguishable from a passing one in a green badge, which is how
   gaps survive.

   > This step used to exempt `pydnp3` and `pyiec61850` as having "no CI-buildable binding".
   > Both now build and run on hosted runners (energy repo, 2026-08-01). `pyiec61850` had
   > quietly started working some time earlier and nobody rechecked; `pydnp3` needed three
   > mechanical fixes to a 2019 binding layer (`scripts/build_pydnp3.sh` in the energy repo).
   > **"Not CI-buildable" is a measurement with an expiry date, not a property.** Re-test it
   > before repeating it — that sentence had been copied forward for months.
7. **Flip status in one PR** (per the sync list above): README (+zh) matrix + validation banner,
   the edition SKILL support matrix, CHANGELOG, and any deck/PPT — and **only** after a real pass.
   Never relabel from a compile-success alone.

> **Honesty note:** a "loopback test exists" is **not** "verified" — it must actually **run and
> pass**. This runbook (and the skill matrix) previously listed IEC-104 as loopback-verified before
> any such test existed; that overclaim was corrected, then earned back with a real 2026-07-13 pass.
