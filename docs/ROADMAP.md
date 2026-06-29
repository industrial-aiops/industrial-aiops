# Industrial-AIOps — Roadmap (pending features)

> Backlog of features to add over time. Grouped by priority. Add to this list as
> ideas land; pull items into a release when picked up. See `docs/HLD.md` for the
> architecture these slot into.

## Editions / connectors (new verticals)
- **energy edition** — IEC 60870-5-104 (`c104`), DNP3 (`pydnp3`), IEC 61850 MMS
  (`libiec61850`). Buyer + regulation differ enough this may graduate to its own
  repo importing core. Add `energy` MCP profile + `iaiops[energy]` bundle.
- **building edition** — BACnet/IP (`BAC0`/`bacpypes3`); facility/HVAC/厂务. Add
  `building` profile + `iaiops[building]` bundle.
- **process edition** — HART-IP connector (process instrumentation) to flesh out
  the existing `process` profile/bundle.
- **PROFINET (read-only)** — DCP discovery / identify / diagnostics / asset only
  (`pnio-dcp`); do NOT attempt RT cyclic data.
- **Modbus-RTU (serial)** — extend the Modbus connector (pymodbus already supports it).
- ❌ Not doing: CC-Link (MC already covers Mitsubishi), PROFIBUS-DP (needs a master
  card, not software-tappable), FL-net (niche, no library).

## Capabilities / intelligence
- **AI downtime root-cause copilot (flagship)** — orchestration over the existing
  read tools + brain (cross-protocol correlation → evidence-cited verdict →
  human-approved, undoable action). Read-first; advisory only; anti-hallucination
  (cite real signals, mark uncertainty). The community's #1 wanted use case.
- **Data-quality watchdog enhancements** — configurable staleness, heartbeat /
  flatline as first-class, bad-quality rollups across endpoints (extends
  historian_health / tag_health).
- **Modbus byte-order auto-detect + vendor register templates** (R4 community pain).
- **UNS governance** — Sparkplug/MQTT schema-drift detection + topic-sprawl /
  naming control (position as a governable neutral data source, not a broker).
- **Tag auto-discovery + semantic modeling + safe rename/alias layer** (the
  integrator's biggest hidden cost; OPC-UA address-space → asset model).

## China / 信创 (market entry for fabs like 华星)
- **Offline / air-gapped install package** (no public-internet dependency).
- **National time-series DB integration** — TDengine / IoTDB as the historian
  sink (don't build our own, don't bind InfluxDB).
- **国产 OS / 芯 validation** — 麒麟/统信, 鲲鹏/海光; declare/replaceable overseas deps.
- **国产 PLC validation** — 汇川 / 台达 / 信捷 over the existing Modbus/Ethernet path.
- **Compliance mapping table** — 《工控系统网络安全防护指南》(分区隔离 / 可审计 /
  双向认证 / 最小权限) as a sales/onboarding artifact.

## Packaging / DX
- **Per-protocol named MCP entry points** (`iaiops-mcp-opcua` …) — sugar; the
  `IAIOPS_MCP` env already delivers the capability.
- **OPC-UA FX / TSN** roadmap watch (2026 certification) as a future credibility point.

## Standing release debt
- ⚠️ PyPI token rotation — give industrial-aiops its own token/account (was reusing
  the vmware one).
- Re-list on skills.sh / ClawHub / MCP Registry under the new org namespace.
