# Industrial-AIOps — Roadmap (pending features)

> Backlog of features to add over time. Grouped by priority. Add to this list as
> ideas land; pull items into a release when picked up. See `docs/HLD.md` for the
> architecture these slot into.

## Editions / connectors (new verticals)
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
- ✅ **building edition** — shipped in v0.6.0 (read-only): BACnet/IP via `BAC0`
  (discover / object-list / read-property / read-points), `building` MCP profile +
  `iaiops[building]` bundle. **Verified 2026-06-30:** fixed a fabricated `whois()`
  call → BAC0's real `who_is()`; who_is/read/disconnect surface verified present
  (contract test guards it). 待核实: live building/HVAC read. Follow-ups:
  present-value writes behind the MOC gate; COV subscriptions; trends.
- **process edition** — HART-IP connector (process instrumentation) to flesh out
  the existing `process` profile/bundle.
- ✅ **PROFINET (read-only)** — shipped in v0.6.0: DCP discovery / identify / asset
  via `pnio-dcp` (`profinet_discover` / `profinet_identify_station` /
  `profinet_station_params` / `profinet_asset_inventory`). No RT cyclic data; DCP
  *Set* (set-name/ip/blink/reset) intentionally not exposed. Follow-up: add DCP Set
  behind the MOC write gate if demand appears.
- **Modbus-RTU (serial)** — extend the Modbus connector (pymodbus already supports it).
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
  conditions for the window instead of requiring injection. Follow-ups: learned
  per-site cause weights, a maintenance-log corpus link, and pulling timestamped
  alarms from a live A&C event source (current OPC-UA surfacing is untimed).
- **Data-quality watchdog enhancements** — configurable staleness, heartbeat /
  flatline as first-class, bad-quality rollups across endpoints (extends
  historian_health / tag_health).
- **Modbus byte-order auto-detect + vendor register templates** (R4 community pain).
- **UNS governance** — Sparkplug/MQTT schema-drift detection + topic-sprawl /
  naming control (position as a governable neutral data source, not a broker).
- ✅ **Tag auto-discovery + semantic modeling + safe alias layer** — shipped:
  `opcua_discover_tags` (`iaiops/connectors/opcua/discovery.py` + `iaiops opcua
  discover`) walks the OPC-UA address space, collects Variable nodes enriched with
  datatype / value / engineering-unit / a heuristic semantic class, groups them into
  assets by browse path, and proposes a clean canonical alias per tag with a
  naming-quality report (alias collisions / cryptic names). Advisory only — no
  server-side rename. Skips ns=0 infrastructure by default. Verified against a real
  asyncua server. Follow-ups: extend the classifier (more domains / vendor profiles);
  cross-protocol model (Modbus register maps → same alias layer); persist/diff the
  adopted alias map over time.

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

## Packaging / DX
- ✅ **Per-protocol named MCP entry points** (`iaiops-mcp-opcua` … + per-edition
  `iaiops-mcp-fab` / `-energy` / `-building` …) — thin shims over `IAIOPS_MCP`,
  data-driven from the profile menu (`mcp_server/entrypoints.py`); reuse the same
  `server.main`. Sugar; the `IAIOPS_MCP` env already delivers the capability.
- **OPC-UA FX / TSN** roadmap watch (2026 certification) as a future credibility point.

## Standing release debt
- ⚠️ PyPI token rotation — give industrial-aiops its own token/account (was reusing
  the vmware one).
- Re-list on skills.sh / ClawHub / MCP Registry under the new org namespace.
