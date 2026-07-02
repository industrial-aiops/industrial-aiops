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
2. **loopback / in-process verified** — real wire against an in-process server on
   localhost (e.g. IEC-104 `c104` loopback; OPC-UA asyncua; HART-IP TCP loopback).
3. **live-gear verified** ← *this runbook* — real physical/virtual device on the
   bench, read end-to-end through the connector.

Only (3) flips the README banner from `待核实` to verified.

## Preview inventory (source of truth: `README.md` validation banner)

| Protocol | Gear needed | Why not in CI |
|----------|-------------|---------------|
| **DNP3** | live outstation (or hardware sim) | `pydnp3` no wheel; needs a real link |
| **IEC-61850** | live IED (substation relay) | MMS server + real dataset |
| **BACnet/IP** | live HVAC / BMS controller | UDP 47808 device on-net |
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
3. `docs/HLD.md` §8.2 — flip the row's 自测 column (`⚠️ → ✅ live <device>`).
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

The other rows remain **待核实 (live gear)** — no BACnet/HART-IP/EtherCAT gear is on
the bench in this environment. This runbook is the standing procedure; the loop does
**not** fabricate a verified status. PLCnext is **route-verified** (in-process
asyncua + faked Modbus, `tests/test_plcnext_route.py`); its *live* row stays here.
