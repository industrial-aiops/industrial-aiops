# Industrial-AIOps — Roadmap (pending features)

> Backlog of features to add over time. Grouped by priority. Add to this list as
> ideas land; pull items into a release when picked up. See `docs/HLD.md` for the
> architecture these slot into.

## Status — 2026-07-02 (what's actually left)

Feature development is essentially **complete and published** (base `iaiops 0.8.0`,
energy `iaiops-energy 0.1.2` — PyPI + GitHub Release + MCP registry). Read paths for
Modbus-RTU / BACnet / DNP3 / IEC-61850 are **live-verified** (container simulators;
each found + fixed real connector bugs). What genuinely remains is NOT feature work:

- **Hardware-in-the-loop verification** (needs physical gear, can't be coded): EtherCAT
  (no software simulator — hardware-only), physical RS-485 (Modbus-RTU), live HVAC
  (BACnet write/COV/trend), live HART-IP gateway, live RTU/IED, live PLCnext.
- **信创 hardware**: 国产 OS (麒麟/统信) · 芯 (鲲鹏/海光) · PLC (汇川/台达/信捷) on-target passes.
- **Out of scope (won't do)**: CC-Link / PROFIBUS-DP / FL-net; IEC-61850 GOOSE/SV;
  PROFINET RT cyclic.
- **Optional depth (nice-to-have, not core)**: DNP3 master link-layer status
  (channel-level done); HART true unsolicited burst subscription (periodic sampling done);
  SIEM forwarder auth header; OPC-UA FX/TSN (2026 cert watch).

Everything below is the detailed backlog with per-item status.

## Editions / connectors (new verticals)
- 📦 **energy edition — split out to [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)**
  (`pip install iaiops-energy`; depends on `iaiops` core). Removed from this repo; see
  `docs/ENERGY-SPINOUT.md`. History below is retained for context.
- ✅ **energy edition** — shipped in v0.6.0 (read-only monitoring): IEC 60870-5-104
  (`c104`), DNP3 (`pydnp3`), IEC 61850 MMS (`pyiec61850`), with the `energy` MCP
  profile + `iaiops[energy]` bundle. **Binding verification pass (2026-06-30):**
  IEC-104 verified against a real c104 loopback link (`tests/test_binding_contracts.py`
  exercises the actual `iec104_session`); IEC-61850 **pin corrected** — the extra
  pointed at the unrelated PyPI `iec61850` (async OOP client, 0 driver symbols); it
  now pins `pyiec61850` (libiec61850 SWIG) and all 14 driver symbols are verified
  present. **Still 待核实:** DNP3 (`pydnp3` ships no wheel + needs a live outstation;
  not yet CI-verifiable) and live-RTU/IED reads. Follow-ups: DNP3 `is_online` live
  link-state via OnStateChange; live-device pass; IEC-61850 GOOSE/SV (out of scope).
  - ✅ **独立仓 spin-out DONE** (HLD §3 D4 / §10 P6): moved to the standalone
    [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) repo
    (published **0.1.2** — PyPI + MCP registry), depending on `iaiops` core. DNP3 +
    IEC-61850 monitor paths were then **live-verified** in that repo. See
    `docs/ENERGY-SPINOUT.md`.
- ✅ **building edition** — shipped in v0.6.0 (read-only): BACnet/IP via `BAC0`
  (discover / object-list / read-property / read-points), `building` MCP profile +
  `iaiops[building]` bundle. **Verified 2026-06-30:** fixed a fabricated `whois()`
  call → BAC0's real `who_is()`; who_is/read/disconnect surface verified present
  (contract test guards it). **Read path verified live 2026-07-02:** a genuine Who-Is
  discover + present-value read round-trip against a real bacpypes3 virtual BACnet/IP
  device on a two-IP subnet in a Linux container (`tests/test_bacnet_live.py`) — this
  also caught + fixed that modern BAC0 (2024+) is async-first (bridged onto a dedicated
  loop, `iaiops/core/runtime/bacnet_async.py`) and that `_norm_device`/`_norm_object`
  must parse bacpypes3's real `IAmRequest` + kebab-case object types. 待核实: live
  building/HVAC read on physical gear (write/COV/trend). **Unreleased:** added
  bounded COV subscriptions (`bacnet_cov_subscribe` — count+timeout capped, always
  unsubscribes) and read-only trend-log reads (`bacnet_read_trend_log` via
  `readRange`); BAC0 `cov`/`cancel_cov`/`readRange` surface contract-verified, live
  COV/trend behaviour still 待核实 (no gear). ✅ present-value write shipped behind the
  MOC gate (`bacnet_write_property`, priority/relinquish, HIGH / dry-run / undo).
- ✅ **process edition — HART-IP connector** — shipped (read-only): `hart_device_identity`
  / `hart_primary_variable` / `hart_dynamic_variables` over HART-IP (UDP/TCP 5094) via the
  `hart` extra (`hart-protocol`), added to the `process` profile/bundle. The HART command
  codec is verified against the real library; live-gateway behaviour stays **待核实**
  (not validated against a live HART-IP server/gateway). Write/device-specific commands
  not exposed.
  - ✅ **TCP transport** — `transport: tcp` selects a stream session (`HartIpTcpSession`)
    alongside the UDP default; reuses the 8-byte framing and **length-delimits** the
    stream by the header `byte_count`. Loopback-verified against an in-process HART-IP
    TCP server (real ACK → real ops/codec). ✅ burst-mode sampling shipped
    (`hart_burst_sample`); live-gateway validation still 待核实; a true unsolicited
    burst subscription stays optional.
- ✅ **PROFINET (read-only)** — shipped in v0.6.0: DCP discovery / identify / asset
  via `pnio-dcp` (`profinet_discover` / `profinet_identify_station` /
  `profinet_station_params` / `profinet_asset_inventory`). No RT cyclic data; DCP
  *Set* — ✅ `profinet_dcp_set` (set-name / set-ip) shipped behind the MOC write gate
  (HIGH risk, `dry_run` default True, undo captures the prior name/ip).
- ✅ **Modbus-RTU (serial)** — shipped: the Modbus connector now selects pymodbus's
  `ModbusSerialClient` when an endpoint sets `transport: rtu` (or a `serial_port:`),
  with `baudrate`/`parity`/`stopbits`/`bytesize` config; the same read ops work over
  RTU and TCP. ✅ **live-serial round-trip VERIFIED 2026-07-02** (socat PTY pair +
  pymodbus RTU server in a container, `tests/test_modbus_rtu_live.py`); a physical
  RS-485/USB device is the only remaining step.
- ✅ **Phoenix Contact PLCnext vPLC (虚拟化 PLC) — route-verified** (no new connector):
  PLCnext exposes its process data over a built-in OPC-UA server (opc.tcp 4840) and a
  Modbus-TCP server, both of which the existing `opcua` + `modbus` connectors already
  speak — no new driver. For convenience it now has a dedicated **`plcnext` MCP profile**
  (`IAIOPS_MCP=plcnext` → opcua+modbus, with an `iaiops-mcp-plcnext` shim), an
  **`iaiops[plcnext]`** pip extra, and a **`phoenix_plcnext_process_be` Modbus register
  template** (documented default GDS/process block, `待核实` per project mapping).
  `tests/test_plcnext_route.py` pins both routes: the OPC-UA path against a **real
  in-process asyncua server** reproducing the `Arp.Plc.Eclr` GDS address space
  (reachability + GDS tag discovery + value read), the Modbus path against a faked
  PLCnext process-data holding block (float32 + status word decode), plus the profile
  resolution and the register template decode. Coverage is declared in
  `iaiops/core/brain/overview.py` (`protocols_supported`). **待核实:** reads against a
  live/physical PLCnext (no gear in CI). Follow-ups: 汇川/台达/信捷 domestic-PLC live pass
  (same reused-Modbus/Ethernet pattern); GDS security (sign/encrypt) once demanded.
- ❌ Not doing: CC-Link (MC already covers Mitsubishi), PROFIBUS-DP (needs a master
  card, not software-tappable), FL-net (niche, no library).

## Capabilities / intelligence
- ✅ **AI downtime root-cause copilot (flagship)** — shipped in v0.5.0 as
  `downtime_root_cause` (`iaiops/core/brain/rca.py` + MCP tool + `iaiops diag rca`):
  temporal cross-protocol correlation (cause-before-effect), noisy-OR confidence,
  evidence-cited verdict, advisory human-approved/undoable action, anti-hallucination
  (`insufficient_evidence` over guessing). ✅ Live evidence auto-collection shipped
  too (`downtime_root_cause_live` / `iaiops diag rca-live`): gathers
  diagnose_dataflow + per-ref sampled series (→ tag_health) + active OPC-UA
  conditions for the window instead of requiring injection. ✅ **Learned /
  configurable per-site cause weights** shipped (Unreleased): `downtime_rca`
  takes a clamped `cause_weights` `{cause: multiplier}` override (neutral 1.0 =
  default), and `iaiops/core/brain/rca_weights.py` (`learn_cause_weights`, MCP
  tool + `iaiops diag learn-weights` / `iaiops diag rca --weights`) derives that
  per-site profile from a labeled incident corpus via an explainable smoothed
  signal→cause precision estimator (Laplace smoothing + per-cause min-sample
  guard + thin-history fall-back to defaults). Remaining follow-ups: a
  maintenance-log corpus link to auto-build that history, and pulling timestamped
  alarms from a live A&C event source (current OPC-UA surfacing is untimed).
- ✅ **Data-quality watchdog enhancements** — shipped: configurable staleness/gap
  per tag + per feed (`staleness_s` / `gap_threshold_s` / `flatline_after_s`),
  flatline + dead-heartbeat surfaced as a first-class scored `liveness` section, and
  a cross-endpoint **fleet rollup** (`data_quality_fleet_rollup` brain fn + MCP tool +
  `iaiops diag dataquality-fleet`) that ranks endpoints by their worst tag and
  aggregates bad-quality counts across endpoints (extends `_rollup_endpoint`).
- ✅ **Modbus byte-order auto-detect + vendor register templates** (R4 community pain) —
  shipped: `modbus_detect_byte_order` (pure decode: scores all candidate word/byte
  orders for a numeric type against a hint/range) + `modbus_list_templates` /
  `modbus_apply_template` (curated vendor register maps → named tags). New
  `iaiops/connectors/modbus/byteorder.py` + `templates.py`, fully unit-tested.
- ✅ **UNS governance** — shipped in v0.6.0: `uns_topic_audit` (naming conformance +
  topic-sprawl: casing collisions / scattered leaves / depth outliers) + `uns_schema_drift`
  (Sparkplug NBIRTH baseline-vs-current → none/additive/breaking). Governable neutral
  source, not a broker. ✅ Follow-up shipped: **live MQTT/Sparkplug subscription** —
  `uns_live_audit` / `sparkplug_live_schema` / `uns_live_drift`
  (`iaiops/connectors/sparkplug/live.py` + `iaiops mqtt uns-live-audit` / `live-schema`
  / `uns-live-drift`) capture topics/BIRTHs from a live broker over a bounded window
  (msg-cap AND timeout) and feed the existing analyzers — closing the loop. Live-broker
  end-to-end path 待核实 (validated vs eclipse-mosquitto locally; no broker in CI).
- ✅ **Tag auto-discovery + semantic modeling + safe alias layer** — shipped:
  `opcua_discover_tags` (`iaiops/connectors/opcua/discovery.py` + `iaiops opcua
  discover`) walks the OPC-UA address space, collects Variable nodes enriched with
  datatype / value / engineering-unit / a heuristic semantic class, groups them into
  assets by browse path, and proposes a clean canonical alias per tag with a
  naming-quality report (alias collisions / cryptic names). Advisory only — no
  server-side rename. Skips ns=0 infrastructure by default. Verified against a real
  asyncua server. Follow-ups: ~~extend the classifier (more domains)~~ ✅ (humidity /
  conductivity / pH / turbidity / density added); ~~cross-protocol model (Modbus register
  maps → same alias layer)~~ ✅; ~~persist/diff the adopted alias map over time~~ ✅
  (`alias_store.py` + `adopt_alias_map` / `diff_alias_map`).
- ✅ **Cross-protocol semantic / asset / alias layer** (the follow-up above) —
  `cross_protocol_asset_model` (`iaiops/core/brain/asset_model.py` + `iaiops analytics
  asset-model`) fuses per-protocol tag feeds (OPC-UA discovery + Modbus register
  templates) into ONE asset/tag model: tags are re-classified with the SAME shared
  classifier (lifted to `iaiops/core/brain/semantics.py`, re-exported by
  `opcua/discovery`), grouped into assets ACROSS protocols, given a canonical
  `<site>.<asset>.<class_or_name>` alias, and checked for alias collisions,
  same-physical-quantity-on-two-protocols overlaps, and cryptic names. Pure +
  advisory (no server-side rename). Follow-ups: persist/diff the adopted alias map;
  add more per-protocol feed adapters as connectors gain tag discovery.

## China / 信创 (market entry for fabs like 华星)
> v0.6.0 shipped the documentation + code artifacts; the **hardware validation**
> rows remain 待核实. See `docs/CHINA.md`.
- ✅ **Offline / air-gapped install** — documented (local wheelhouse, `pip install
  --no-index`); pure-Python core + per-protocol extras make it work without a
  public index. (docs/CHINA.md §2.)
- ✅ **National time-series DB integration** — `historian_push` sink for TDengine
  (`iaiops[tdengine]`) + IoTDB (`iaiops[iotdb]`); no own store, no InfluxDB bind.
  **Live-verified 2026-06-30** against containerized servers (write→read round-trip):
  IoTDB via the real `IoTDBSink`; TDengine after fixing a real bug — the `value`
  column is a TDengine reserved word and must be back-quoted in the `CREATE STABLE`
  DDL (mock tests never hit the live parser).
- ⏳ **国产 OS / 芯 validation** — 麒麟/统信, 鲲鹏/海光: validation matrix documented
  (docs/CHINA.md §3), **待核实** (not hardware-verified). Per-protocol extras make
  overseas deps replaceable.
- ⏳ **国产 PLC validation** — 汇川 / 台达 / 信捷 over the existing Modbus/S7 paths;
  documented, **待核实**.
- ✅ **Compliance mapping table** — `compliance_mapping` tool + `iaiops compliance`
  CLI: 《工控系统网络安全防护指南》(分区隔离 / 可审计 / 双向认证 / 最小权限 / 数据保护 /
  自主可控) with honest per-control status + gaps.
- ✅ **Compliance mapping expansion (等保 2.0 / IEC 62443)** — each control now carries a
  `crosswalk` to the matching 等保 2.0 (GB/T 22239-2019) control class and IEC 62443
  foundational requirement (FR1–FR6); surfaced by a new `compliance_frameworks` MCP tool
  (governed, read-only) and `docs/CHINA.md §5.1`. Onboarding/audit reference, not a
  certification. ✅ per-level (等保 二级/三级) control deltas shipped
  (`compliance_dengbao_levels` MCP tool + `iaiops compliance --dengbao-level`).

## Security / governance (shipped 0.8.0)
- ✅ **双向认证 mTLS** — OPC-UA certificate security mode (`set_security_string`
  policy/mode + client cert/key, optional server cert) + MQTT CA/client-cert
  (`tls_set`); `TargetConfig` cert path fields; compliance「双向认证」→ addressed.
  Live cert validation on real gear 待核实.
- ✅ **Audit → SIEM forwarding** — `iaiops/core/governance/forward.py` +
  `iaiops audit forward --sink syslog|http` (at-least-once since-cursor). Follow-up:
  auth header / bearer token for authenticated SIEM collectors.
- ✅ **Secret rotation** — `iaiops secret rotate` re-encrypts the store under a new
  master password (read from `IAIOPS_NEW_MASTER_PASSWORD`, never argv).

## Packaging / DX
- ✅ **Per-protocol named MCP entry points** (`iaiops-mcp-opcua` … + per-edition
  `iaiops-mcp-fab` / `-energy` / `-building` …) — thin shims over `IAIOPS_MCP`,
  data-driven from the profile menu (`mcp_server/entrypoints.py`); reuse the same
  `server.main`. Sugar; the `IAIOPS_MCP` env already delivers the capability.
- **OPC-UA FX / TSN** roadmap watch (2026 certification) as a future credibility point.

## Standing release debt
- ⚠️ **PyPI token** — the same token was re-exposed in chat for the 0.7.0 AND 0.8.0
  publishes and MUST be revoked; mint a fresh industrial-aiops token, keep it in
  `~/.pypirc` / a secret manager, never paste it into a conversation.
- ✅ Published all channels: **iaiops 0.8.0** + **iaiops-energy 0.1.2** on PyPI, GitHub
  Releases (v0.8.0 / v0.1.2), and the MCP registry (`io.github.industrial-aiops/iaiops`
  + `…/iaiops-energy`) under the industrial-aiops org (2026-07-02). Base 0.7.0 was also
  on ClawHub / skills.sh (2026-06-30).
