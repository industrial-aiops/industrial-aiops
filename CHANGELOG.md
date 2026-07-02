# Changelog

## 0.9.0 — 2026-07-02

### Security — governance hardening (from full audit)
- **Approver gate now enforced out-of-the-box**: with no `risk_tiers` in `~/.iaiops/rules.yaml`,
  high/critical risk operations default to tier `dual` (approver required, rule `builtin_default`)
  instead of tier `none`. `iaiops init` writes a commented starter `rules.yaml` with an explicit
  `risk_tiers` gate. Dead `risk_requires_confirmation()` removed.
- **Policy engine fails closed**: a malformed or deleted `rules.yaml` now retains the
  last-known-good rule set (audited as `policy_load_failed`) instead of silently reverting
  to allow-all.
- **Policy kill switch constrained**: renamed to `IAIOPS_POLICY_DISABLED` (legacy
  `OPCUA_POLICY_DISABLED` still works with a deprecation warning) and it never bypasses
  high/critical risk checks.
- **One-shot approval tokens**: `iaiops approve <tool> --endpoint <ep> --by <name> [--ttl]`
  writes a single-use, TTL-bound approval consumed by the next matching governed call
  (`approver_source="token"` in audit). The static `OPCUA_AUDIT_APPROVED_BY` env var remains
  as a deprecated fallback (`approver_source="env"`, once-per-process warning).
- **Audit fails closed for writes**: high/critical operations are denied (`audit_unavailable`)
  when the audit row cannot be written; low/medium proceed with a warning.
- **Audit tamper-evidence**: SHA-256 hash chain (`prev_hash`/`row_hash`) on every audit row +
  `iaiops audit verify` to walk the chain and report the first broken link.
- **SIEM forwarding hardened**: bare hosts default to `https://`, loud warnings on plaintext
  sinks, optional `Authorization: Bearer` via `IAIOPS_FORWARD_TOKEN`.
- **Startup governance assertion**: the MCP server refuses to start if any registered tool
  lacks `_is_governed_tool`.
- **Plaintext secret remnants removed**: `.env.migrated` is rewritten with secret values
  stripped after migration; `iaiops doctor` reports an ERROR while a plaintext `.env` is in
  use and warns when an OPC-UA target pairs `username` with `security_mode: None`.

### Fixed
- **Connect timeouts**: new `TargetConfig.timeout_s` (default 10 s, `IAIOPS_TIMEOUT_S` fleet
  override) threaded into the OPC-UA / S7 / MC / EtherNet-IP builders so an unroutable host
  no longer blocks a tool call for the OS TCP timeout.
- **SKILL.md brought back in sync with the code**: write-tool count corrected (8, not 6),
  `profinet_dcp_set` and `bacnet_write_property` documented as MOC-gated high-risk writes
  (the skill previously claimed they didn't exist), ~23 missing tools added incl. a HART-IP
  section, energy-protocol triggers now redirect to `iaiops-energy`. A new
  `tests/test_skill_sync.py` gate keeps skill and registered tools from drifting again.
- `server.json`: title corrected to "Industrial-AIOps", `environmentVariables` declared
  (`IAIOPS_MCP`, `IAIOPS_CONFIG`, `IAIOPS_MASTER_PASSWORD`).

### Added — queryability layer (A2)
- **Local SQLite sink** (`historian_push(sink="sqlite")` / `iaiops historian push --sink
  sqlite`): normalized samples land in a queryable on-box store `~/.iaiops/data.db`
  (WAL, 0600/0700 hardening, `samples(ts, endpoint, protocol, tag, value, quality, unit)`
  + indexes); keeps non-numeric values as text (the TSDB sinks stay numeric-only).
- **`iaiops export csv|sqlite|parquet`** — open-format export FROM the local store with
  `--since/--until/--endpoint/--tag/--limit` filters (fail-fast validation). CSV/SQLite
  are stdlib-only; Parquet via the new optional extra `iaiops[export]` (pyarrow, lazy
  import with a teaching error). Governed MCP counterpart: `export_data` ([READ][risk=low],
  bounded ≤200-row inline preview, returns path + row count).
- **Prometheus/Grafana bridge** — `iaiops metrics serve --port 9184` exposes `/metrics`
  (text format 0.0.4, stdlib http.server): `iaiops_tag_value{endpoint,protocol,tag,unit}`
  gauges (latest value per tag) + `iaiops_samples_written_total` /
  `iaiops_audit_events_total` / `iaiops_tool_errors_total` counters. Binds 127.0.0.1 by
  default; explicit `--host 0.0.0.0` warns loudly. Recipe: `docs/GRAFANA.md`.
### Added — compliance report generation (A3)
- **`iaiops compliance report --out report.md [--html] [--site NAME] [--level l2|l3]`**:
  renders the existing compliance crosswalk into a deliverable document — title-page
  metadata (site / date / iaiops version), per-pillar 等保 2.0 L2/L3 status table,
  IEC 62443 FR1–6 crosswalk, honest gap list, and a governance-controls appendix
  (audit hash chain / approval tokens / dry-run+undo / mTLS). Markdown by default,
  `--html` via a stdlib converter (no new deps). Onboarding aid, 非认证.
- **`iaiops compliance evidence --out bundle.zip [--since ISO] [--until ISO]`**:
  audit-evidence zip with deterministic member names — `audit_rows.jsonl` (secrets
  already redacted upstream), `chain_verification.json` (hash-chain walk),
  `rules.yaml` (if present), `doctor_summary.json`, `manifest.json`. Output paths
  reject `..` traversal; parent dirs created 0700, bundle written 0600.
- New governed MCP tools `compliance_report` (inline markdown capped at ~400 lines,
  else write to `out_path`) and `compliance_evidence_bundle`, both [READ][risk=low].
### Added — ISA-18.2 alarm flood analysis (A4)
- **New brain module `iaiops.core.brain.alarm_flood`** (pure, no I/O): `detect_floods`
  (flood *episodes* — start/end/count/peak rate/top contributors, per ISA-18.2's
  ≥10 alarms/10 min per operator), `chattering_alarms` (ACTIVE↔CLEARED cycle counting),
  `stale_standing_alarms` (continuously active > 24 h), `flood_summary`
  (percent-time-in-flood + avg/peak rate vs the ~1-2 alarms/10 min target, honest
  `insufficient_data` handling), and `rationalization_worksheet` (CSV-exportable rows).
- **New governed MCP tools** (`alarm_flood_analysis`, `alarm_rationalization_worksheet`,
  both `[READ][risk=low]`, bounded output with truncation flags): analyze injected events
  or collect live via the same OPC-UA active-condition scan the RCA copilot uses
  (`rca_collect.collect_active_alarms`, polled over `duration_s`).
- **New CLI commands**: `iaiops diag alarm-flood` and `iaiops diag alarm-worksheet`
  (JSON events in; deep report out, or a CSV worksheet via `--out`).
### Added — water treatment edition (A9)
- **`water` profile** (水处理): `IAIOPS_MCP=water` exposes exactly modbus + opcua + hart
  (+ the always-on brain), with a matching `iaiops-mcp-water` console script and an
  `iaiops[water]` extra that references the per-protocol extras (no duplicated pins).
- **Water-domain semantics**: the tag classifier gains dissolved_oxygen (DO/溶解氧),
  orp (氧化还原/redox), chlorine (余氯/总氯), ammonia (氨氮/NH3), suspended_solids
  (TSS/MLSS/悬浮物), membrane_pressure (TMP/跨膜压差), uv_intensity (紫外), dosing
  (加药) and aeration (曝气/风机/blower) classes, plus 流量/液位 hints on flow/level.
  Ambiguous bare tokens (do/tmp/orp) stay underscore-/context-guarded — honest `other`
  over a confident-but-wrong class.
- **Water-industry Modbus register templates**: `eh_promag_flowmeter` (E+H Promag
  process values), `hach_sc_controller` (pH/DO/turbidity sensor slots) and
  `generic_dosing_pump` (加药泵 block). All three ship with explicit 待核实 caveats and
  placeholder offsets where no fixed public vendor map exists — no invented "verified"
  addresses.
- New `tests/test_water_edition.py` pins the profile/entrypoint/extra contract, the
  water tag classes and the template catalog.

## 0.8.0 — 2026-07-02

### Changed — energy edition split out
- **The energy edition (变电/电力: IEC-104 / DNP3 / IEC-61850) moved to its own
  package**, [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)
  (`pip install iaiops-energy`), which depends on `iaiops` for the shared core (governance
  / brain / runtime / normalized model) and MCP server. Removed from this repo: the three
  connectors + their session builders (`connection.py`), MCP tool modules, CLI apps, the
  `energy` MCP profile + `iaiops-mcp-energy` entrypoint + `iaiops[iec104|dnp3|iec61850|energy]`
  extras, and `common_address`/`master_address` on `TargetConfig`. Base is now **12 field
  protocols**. See `docs/ENERGY-SPINOUT.md`. Building edition + the rest are unchanged.

### Added — Phoenix Contact PLCnext vPLC (虚拟化 PLC)
- **Route-verified** over the existing OPC-UA + Modbus connectors (no new driver): a
  dedicated `plcnext` MCP profile (`IAIOPS_MCP=plcnext`, `iaiops-mcp-plcnext`, `iaiops[plcnext]`),
  a `phoenix_plcnext_process_be` Modbus register template, and `tests/test_plcnext_route.py`
  (real in-process asyncua `Arp.Plc.Eclr` server + faked Modbus). Live PLCnext read stays 待核实.

### Added — compliance crosswalk
- **Compliance mapping expanded** with a 等保 2.0 (GB/T 22239) + IEC 62443 (FR1–6)
  crosswalk: new governed `compliance_frameworks` MCP tool + `iaiops compliance --frameworks`
  CLI; each control now carries a `crosswalk`. See `docs/CHINA.md §5.1`.
- **等保 2.0 per-level deltas** — new governed `compliance_dengbao_levels` MCP tool +
  `iaiops compliance --dengbao-level <l2|l3|二级|三级>` CLI show, per pillar, the 二级
  baseline vs the 三级 增量 and how far iaiops moves you toward it (honest status/gap
  reused from `CONTROLS`). Onboarding aid, not a certification.

### Added — connector depth
- **HART `hart_burst_sample`** (governed, read-only, risk=low) — actively samples the
  periodically-published (burst) variables (command 3) N times over one session; a
  true unsolicited HART-IP burst subscription stays 待核实.
- **Modbus vendor register templates** — added `carlo_gavazzi_em24` (scaled int32,
  CDAB), `huawei_sun2000_inverter` and `growatt_inverter` (int32/uint32/uint16 with
  scaling); each carries a `待核实` caveat and a base-relative span within the 125-reg
  read limit.

### Added — protocols
- **HART-IP TCP transport** — the HART connector now speaks HART-IP over **TCP**
  (port 5094) in addition to UDP. An endpoint selects it with `transport: tcp`
  (UDP stays the default); `_build_hart_ip_client` picks the new
  `HartIpTcpSession` vs the existing UDP `HartIpSession`. Both reuse the same
  transport-agnostic 8-byte framing (`frame_message`/`parse_message`) and the same
  session-initiate → token-passing → close sequence. The TCP session correctly
  **length-delimits** the byte stream — it reads the 8-byte header, parses
  `byte_count`, then reads exactly `byte_count - 8` more bytes (never trusting a
  single `recv` to return a whole frame). Config gained a per-protocol transport
  resolver (`_hart_transport`: `tcp` only when explicit, else `udp`); the shared
  `TargetConfig.transport` default is now `""` ("protocol default": Modbus→tcp,
  HART→udp). **Loopback-verified**: an in-process HART-IP TCP server thread
  round-trips a real HART long-frame ACK through the REAL ops/codec path to the
  primary variable. Live-gateway behaviour stays 待核实; write/device-specific
  commands remain unexposed.

### Added — RCA intelligence
- **RCA learned / configurable per-site cause weights** — the downtime
  root-cause copilot (`iaiops/core/brain/rca.py`, `downtime_rca`) gains an
  optional `cause_weights` `{cause: multiplier}` override that scales each
  cause's evidence (1.0 = neutral, today's shipped behaviour) before the noisy-OR,
  so a site can up-/down-weight causes its own history has shown to be more/less
  reliable. Overrides are validated + clamped at the boundary (unknown causes /
  non-numeric weights teach an error). New pure module
  `iaiops/core/brain/rca_weights.py` (`learn_cause_weights`) derives that profile
  from a labeled incident corpus (`[{cause, signals}]`) with a simple, explainable
  estimator — smoothed signal→cause precision relative to chance — plus anti-overfit
  guards (Laplace smoothing, a per-cause min-sample guard, and a fall-back to the
  shipped defaults when history is thin) and a human-readable rationale. Wired as a
  new MCP brain tool `learn_cause_weights` (`@governed_tool(risk_level="low")`), a
  `cause_weights` arg on `downtime_root_cause`, and CLI
  `iaiops diag learn-weights --input incidents.json` + `iaiops diag rca --weights
  profile.json`. Pure/deterministic and advisory only — it tunes ranking, never
  executes anything.

### Added — building edition (BACnet)
- **BACnet bounded COV subscriptions + read-only trend-log reads** — two new
  read-only tools on the BACnet connector (`iaiops/connectors/bacnet/ops.py`):
  - `bacnet_cov_subscribe` — a BOUNDED change-of-value capture: subscribes to one
    object's COV (`BAC0.lite.cov`), collects up to `max_notifications` OR until
    `timeout_s` (whichever first), then ALWAYS unsubscribes (`cancel_cov` in a
    `finally`). Hard-capped by both count and wall-clock — never an open
    subscription. Reports `terminated_reason` (`max_notifications`|`timeout`).
  - `bacnet_read_trend_log` — reads a device's BACnet `TrendLog` object's buffered
    log records via a single bounded `readRange` (RangeByPosition; `newest_first`
    reverses the search), normalizing each record to `{timestamp, value}`.
  - Both exposed as governed MCP tools (`@governed_tool(risk_level="low")`) and CLI
    `iaiops bacnet cov` / `iaiops bacnet trend`; added to the overview catalog.
  - The BAC0 `cov` / `cancel_cov` / `readRange` surface is VERIFIED against the
    installed BAC0/bacpypes3 (contract tests `test_bacnet_bac0_surface` +
    `test_bacnet_bac0_cov_signature`); live HVAC COV/trend behaviour stays 待核实
    (no gear). Unit-tested against a mocked network, incl. the bounded-termination
    guarantee and the always-unsubscribe invariant.

### Added — tag intelligence
- **Adopted alias-map persistence + cross-run diff** — `iaiops/core/brain/alias_store.py`
  + MCP tools `adopt_alias_map` / `diff_alias_map` + `iaiops analytics` CLI. Persists the
  adopted canonical alias map per site (JSON under `~/.iaiops/aliases/<site>.json`, dirs
  created with safe perms) and `diff_alias_map` reports **added / removed / renamed**
  (same ref, new alias) / **reclassified** (same ref, new class) tags between the stored
  map and a fresh discovery / cross-protocol asset-model run → a stable/changed verdict.
  Pure + bounded file I/O (validated at the boundary).
- **Extended semantic classifier** — `_CLASS_HINTS` in `iaiops/core/brain/semantics.py`
  gains humidity / conductivity / pH / turbidity / density (+ more unit/synonym hints) so
  fewer real tags fall to `other`. Existing classifications are unchanged (ordering rules
  intact; the OPC-UA discovery + asset-model classifier tests pass unmodified).

### Added — CI / DX
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — runs the release quality
  gate on push to `main` and on every pull request. A `gate` job (Python 3.11 +
  3.12 matrix, `uv sync --extra all`) runs `pytest -q`, `ruff check .`, and
  `bandit -q -r iaiops mcp_server` (must stay 0 Medium+). A second
  `integration-contracts` job (linux, 3.12) installs the pure-python energy/TSDB/
  HART extras that ship linux wheels (`c104`, `pyiec61850` `--pre`, `apache-iotdb`,
  `taospy`, `BAC0`, `hart-protocol`) and runs the `integration`-marked library-API
  contract tests, so the `importorskip`-gated bindings actually execute on linux.
  Hardware/root-only protocols (EtherCAT/PROFINET raw L2 sockets, live serial,
  native-build `pydnp3`) self-skip — documented inline in the workflow.

### Added — cross-protocol intelligence
- **Cross-protocol semantic / asset / alias layer** — new pure brain module
  `iaiops/core/brain/asset_model.py` (`cross_protocol_asset_model`), MCP brain
  tool `cross_protocol_asset_model` (`@governed_tool(risk_level="low")`) and CLI
  `iaiops analytics asset-model --input feeds.json --site <site>`. Fuses
  per-protocol tag *feeds* (OPC-UA `opcua_discover_tags` descriptors + Modbus
  `modbus_apply_template` tags, or any normalized tags) into ONE unified
  asset/tag model: tags are grouped into assets **across** protocols (a `Line1`
  OPC-UA folder + a `Line1` Modbus block become one asset), each is given a
  canonical cross-protocol alias `<site>.<asset>.<class_or_name>`, and a
  cross-protocol naming-quality view reports **alias collisions**, the **same
  physical quantity exposed by two protocols** (`cross_protocol_overlaps`), and
  **cryptic names**. Pure (inputs are tag dicts) and advisory only — aliases are
  SUGGESTIONS, never a server-side rename (OT-dangerous).

### Changed — shared semantics (no behaviour change)
- Lifted the tag **semantic classifier** (`classify_tag`) and **alias scheme**
  (`suggest_alias` / `alias_segment`) out of `iaiops/connectors/opcua/discovery.py`
  into a shared home `iaiops/core/brain/semantics.py`. `opcua/discovery`
  re-exports them so its public API is unchanged, and the cross-protocol layer
  imports the SAME functions — one taxonomy, no divergent fork. Existing OPC-UA
  discovery tests pass unchanged.

### Added — UNS governance (live MQTT/Sparkplug subscription)
- **Live UNS governance bridge** — closes the loop on UNS governance: until now
  `uns_topic_audit` / `uns_schema_drift` only analyzed data the caller *provided*
  (a topic list, two NBIRTH snapshots). New `iaiops/connectors/sparkplug/live.py`
  captures those inputs from a LIVE broker over a BOUNDED window (the same
  `ops._collect` collector — up to `max_msgs` messages OR `duration_s`, whichever
  first; never an open-ended loop) and feeds them straight into the analyzers:
  - `uns_live_audit(endpoint, topic, duration_s, max_msgs, …)` — captures the live
    topic tree then runs the naming-conformance + topic-sprawl audit; returns the
    audit plus a `capture` block (observed_messages / unique_topics / topics).
  - `sparkplug_live_schema(endpoint, topic, duration_s, max_msgs)` — captures
    NBIRTH/DBIRTH and builds the drift-ready `{node:{metric:datatype}}` dict
    (node = group/edge[/device]) that `uns_schema_drift` accepts.
  - `uns_live_drift(baseline, endpoint, …)` — captures the live schema and diffs it
    against a provided baseline (none/additive/breaking).
  All three are governed MCP tools (`@governed_tool(risk_level="low")`), exposed on
  the CLI as `iaiops mqtt uns-live-audit` / `live-schema` / `uns-live-drift`, and
  added to the `mqtt` protocol's overview catalog.
- **paho 2.x verified** — the bounded collector runs through paho-mqtt 2.1.0's
  `CallbackAPIVersion.VERSION2` callback surface (already used by the connection
  layer). Unit tests INJECT messages through the assigned `on_message` callback and
  assert the capture terminates on BOTH the message cap and the timeout (no live
  broker needed). One opt-in `integration`-marked end-to-end test publishes to and
  captures from a real broker — 待核实: validated locally against eclipse-mosquitto,
  skipped in CI (no broker) and not validated against a production Sparkplug host.

## 0.7.0 — HART-IP, tag discovery, data-quality & Modbus depth (2026-06-30)

New read-only **HART-IP** process-instrumentation connector, **OPC-UA tag
auto-discovery + semantic modeling**, data-quality watchdog enhancements,
Modbus byte-order auto-detect / vendor templates / RTU serial, and per-protocol
named MCP entry points — plus a live binding-validation pass that fixed three
real defects mocks never caught (see the 0.6.0 validation notes below). All
read-first; previews carry honest `待核实` caveats.

### Added — packaging / DX
- **Per-protocol & per-edition named MCP entry points** — convenience console
  scripts `iaiops-mcp-opcua`, `iaiops-mcp-modbus`, … (one per protocol) plus
  `iaiops-mcp-fab` / `-factory` / `-process` / `-energy` / `-building` (named
  profiles). Each is a thin shim (`mcp_server/entrypoints.py`) that injects the
  equivalent `IAIOPS_MCP=<name>` selection then starts the **same** server via
  `server.main` — no server logic duplicated. The shim set is generated
  data-driven from `PROTOCOL_MODULES` + `NAMED_PROFILES`, so it can't drift from
  the menu, and produces an identical registered tool set to `IAIOPS_MCP=<name>`.
  Pure sugar — the `IAIOPS_MCP` env var already delivered the capability.

### Added — Modbus connector
- **Modbus byte-order auto-detect + vendor register templates** (R4 community pain) —
  `modbus_detect_byte_order` (PURE decode logic, no device): decodes a raw register
  block under every candidate word/byte order for a numeric type (uint16/int16/
  uint32/int32/float32 → AB/BA and ABCD/DCBA/BADC/CDAB) and scores them against a
  known `hint` value and/or a plausible `[value_min, value_max]` band, returning the
  best order + confidence. Plus `modbus_list_templates` / `modbus_apply_template`: a
  curated set of vendor register maps (generic big-endian / word-swapped float blocks,
  Eastron SDM630 energy meter, Schneider PM5xxx power meter) that decode a block into
  named engineering tags. New modules `iaiops/connectors/modbus/byteorder.py` +
  `templates.py`. Fully unit-tested.
- **Modbus-RTU (serial) transport** — the Modbus connector now speaks Modbus-RTU over
  a serial line as well as Modbus-TCP. Endpoints set `transport: rtu` (or just a
  `serial_port:`) with `baudrate` / `parity` / `stopbits` / `bytesize`; the connection
  layer builds pymodbus's `ModbusSerialClient` and the same read ops (holding / input /
  coils / discrete) work unchanged. Client construction + config plumbing are
  unit-verified (monkeypatched pymodbus client). **待核实:** the live-serial round-trip
  needs real RS-485/USB hardware and is not CI-verifiable.

### Added — verticals & protocols
- **HART-IP connector (read-only, process edition)** — `hart_device_identity` /
  `hart_primary_variable` / `hart_dynamic_variables` MCP tools + `iaiops hart` CLI
  (`iaiops/connectors/hart/`), over HART-IP (UDP 5094) via the `hart` extra
  (`hart-protocol`); added to the `process` profile/bundle. The HART command codec
  (build/parse) is **verified offline** against the real library; the **HART-IP wire
  transport is 待核实** (not validated against a live HART-IP server/gateway). Write
  and device-specific commands are intentionally NOT exposed (OT-dangerous on live
  instrumentation).

### Added — intelligence layer
- **Data-quality watchdog enhancements** (`iaiops/core/brain/dataquality.py`) — extends
  the data-trust scorecard with: (1) **configurable staleness/gap per tag and per feed**
  (`staleness_s` / `gap_threshold_s`, with a feed-level `staleness_s` default) so a slow
  daily counter is not judged like a 1Hz sensor, plus `flatline_after_s` to flag a stuck
  value by its longest stall; (2) **flatline / dead-heartbeat as a first-class scored
  `liveness` section** in the scorecard output (no longer buried in per-tag flags),
  reusing `_longest_stall`; (3) **cross-endpoint fleet rollup** — new
  `data_quality_fleet_rollup` brain fn + MCP tool + `iaiops diag dataquality-fleet` CLI
  that ranks endpoints by their single worst tag and aggregates bad-quality tag counts
  across every endpoint (extends the per-endpoint `_rollup_endpoint`). Pure analysis.
- **OPC-UA tag auto-discovery + semantic modeling** — `opcua_discover_tags` MCP tool
  + `iaiops opcua discover` CLI (`iaiops/connectors/opcua/discovery.py`): walks the
  address space, collects every Variable node enriched with datatype / value /
  engineering-unit, infers a heuristic semantic class (temperature / pressure / flow /
  setpoint / alarm / state / …), groups tags into assets by browse path, and proposes
  a clean canonical alias per tag with a naming-quality report (alias collisions /
  cryptic names). Advisory + read-only — no server-side rename. Skips OPC-UA ns=0
  infrastructure by default. Verified against a real in-process asyncua server.

## 0.6.0 — New verticals & protocols (PROFINET, energy, building, 信创) + intelligence

Breadth release: new field protocols and per-industry editions, China-market entry
artifacts, and two new read-only intelligence layers. Same read-first stance and
preview / mock-or-sim caveat. (Also includes a code-review hardening pass — see below.)

### Added — intelligence layer
- **Data-quality watchdog** — `data_quality_scorecard` (fleet data-TRUST rollup:
  scores each tag 0-100 on staleness / **dead heartbeat** / bad-quality / flatline /
  gaps / anomaly, rolled up per endpoint + fleet with ranked worst offenders) and
  `heartbeat_health` (first-class watchdog-liveness check). Pure analysis; also feeds
  the downtime root-cause copilot. CLIs `iaiops diag dataquality` / `iaiops diag heartbeat`.
- **UNS governance** — `uns_topic_audit` (UNS naming conformance + topic-sprawl:
  casing collisions, scattered leaves, depth outliers, duplicates → clean/minor/
  sprawling) and `uns_schema_drift` (Sparkplug NBIRTH baseline-vs-current →
  none/additive/breaking). CLIs `iaiops mqtt uns-audit` / `iaiops mqtt uns-drift`.

### Fixed (code-review hardening)
- **`iec61850` extra had a fabricated version pin** (`>=1.5` — uninstallable; PyPI tops
  out at 0.12.x) that broke `iaiops[energy]` resolution → corrected to `>=0.10,<1`.
- **`secsgem` was missing from `SUPPORTED_PROTOCOLS`** since v0.4.0 — config rejected
  every secsgem endpoint, making that connector unreachable → fixed + fully wired into
  the capability map.
- **RCA copilot crashed on mixed naive/aware timestamps** (operator's naive `start` vs a
  device's `...Z` alarm) → timestamp parsing now coerces naive→UTC everywhere.
- **PROFINET / BACnet / IEC-104 raised raw tracebacks** on the most common real failure
  (raw-socket permission / UDP bind) because the client was built outside the session
  `try` → builds moved inside; failures now translate to teaching errors.
- **SQL-injection hole** in the TDengine sink (unescaped timestamp; identifiers) → fixed.
  Plus: DNP3 integrity-poll harvested the wrong handler; IoTDB wrote local-tz/epoch-0;
  chattering alarms inflated RCA confidence; live sink errors escaped the error contract.
  15 regression tests added for the previously-untested paths.

### Fixed (binding validation pass, 2026-06-30)
Ran the preview/待核实 bindings against **real libraries + containerized servers**
(not mocks) — which surfaced three real bugs the mock suite could never catch:
- **`iec61850` extra pointed at the wrong PyPI distribution.** The prior pin
  `iec61850>=0.10,<1` resolves to an unrelated async-OOP client that exposes **none**
  of the `IedConnection_*` SWIG symbols the driver calls (0/14). Re-pinned to
  **`pyiec61850`** (the real libiec61850 SWIG binding, linux-only wheel); all 14
  driver symbols verified present, and the driver/connection imports now use it.
- **BACnet called a fabricated `whois()`** — BAC0 exposes `who_is()`; the mock fake
  duck-typed the wrong name, so it would have `AttributeError`'d against real gear.
- **TDengine `CREATE STABLE` used `value` as a column name** — a TDengine reserved
  word the live parser rejects with a syntax error → back-quoted in DDL.
- **Verified live:** IEC-104 (real c104 loopback link via `iec104_session`), IoTDB &
  TDengine (write→read round-trip via the real sinks). **Still 待核实:** DNP3
  (`pydnp3` has no wheel + needs a live outstation) and live-RTU/IED reads.
- **New guards:** `tests/test_binding_contracts.py` (per-binding library-API contract
  tests, `importorskip`-gated — run when an extra is installed) and
  `tests/test_protocol_consistency.py` (cross-registry meta-test that would have caught
  the historical `secsgem`-missing-from-`SUPPORTED_PROTOCOLS` regression).

### Added — verticals & protocols
- **PROFINET connector (read-only)** — layer-2 **PROFINET-DCP** discovery/identify
  via the optional `pnio-dcp` extra (`pip install iaiops[profinet]`):
  `profinet_discover` (DCP IdentifyAll — one broadcast surfaces every station on the
  segment), `profinet_identify_station` (by name-of-station), `profinet_station_params`
  (targeted DCP Get by MAC), and `profinet_asset_inventory` (register with
  IO-controller/IO-device role decoding). **Discovery + identify only** — no RT cyclic
  process data, and the disruptive DCP *Set* services (set-name/ip/blink/reset) are not
  exposed. Needs raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the PROFINET
  subnet; added to the `factory` profile + bundle. Mock-tested, not yet hardware-verified.
- **Energy edition** — three read-only substation/utility telecontrol connectors,
  an `energy` MCP profile (`IAIOPS_MCP=energy`), and the `iaiops[energy]` bundle:
  - **IEC 60870-5-104** (`iaiops[iec104]`, `c104`): `iec104_connection_info`,
    `iec104_interrogate` (general interrogation), `iec104_read_point`.
  - **DNP3** (`iaiops[dnp3]`, `pydnp3`/opendnp3): `dnp3_link_status`,
    `dnp3_integrity_poll` (Class 0/1/2/3 database grouped by measurement type).
  - **IEC 61850 MMS** (`iaiops[iec61850]`, libiec61850): `iec61850_device_directory`,
    `iec61850_browse`, `iec61850_read` (object-reference + functional constraint).
  - **Monitor direction only** — control commands (C_SC/C_DC, CROB, Oper/SBO) and
    IEC-61850 GOOSE/SV are not exposed. **⚠️ Preview / 待核实**: library bindings are
    unverified against live RTUs/IEDs and kept out of `iaiops[all]` (iec61850 needs
    libiec61850 built; pydnp3 builds a native ext). Largest validation debt in the line.
- **Building edition** — **BACnet/IP** (ASHRAE 135) read-only facility/HVAC monitoring
  via the `iaiops[bacnet]` extra (BAC0/bacpypes3), the `building` MCP profile
  (`IAIOPS_MCP=building`), and the `iaiops[building]` bundle: `bacnet_discover`
  (Who-Is), `bacnet_object_list`, `bacnet_read_property`, `bacnet_read_points`
  (present-value snapshot of analog/binary/multistate points). Read-only — present-value
  writes are not exposed. **⚠️ Preview / 待核实**: BAC0 binding unverified against live gear.
- **信创 / China entry** — `compliance_mapping` (《工控系统网络安全防护指南》 ↔ iaiops
  governance self-assessment with honest per-control status), a national-TSDB
  historian sink `historian_push` (write collected telemetry to **TDengine**
  `iaiops[tdengine]` or **Apache IoTDB** `iaiops[iotdb]` — data egress to the
  operator's own historian, not a control write), CLIs `iaiops compliance` /
  `iaiops historian push`, and **docs/CHINA.md** (air-gapped wheelhouse install,
  国产 OS/芯/PLC validation matrix, compliance reference). **⚠️ 待核实**: 国产
  OS/芯/PLC and the TSDB write paths are documented but not hardware-verified.

### Notes
- 90 tools across 14 protocols (incl. 2 信创/compliance + 4 new intelligence tools).
  Still **preview** — mock/sim validated; the energy, building, and 信创 paths are
  unverified against live equipment (see docs/CHINA.md for the validation backlog).

## 0.5.0 — AI downtime root-cause copilot

The flagship cross-protocol intelligence step: orchestrate the existing read
tools + brain into an **evidence-cited, advisory** root-cause verdict for a
downtime/incident window. Read-first, mock/sim preview — unchanged stance.

### Added
- **`downtime_root_cause`** (brain `iaiops/core/brain/rca.py`, MCP tool, and
  `iaiops diag rca`) — correlates whatever evidence a site supplies (alarm events,
  tag samples, a `diagnose_dataflow` verdict, a machine-state series) around an
  incident window and ranks candidate causes. Highlights:
  - **Temporal correlation** — a cause precedes its effect, so signals *before*
    onset (within a configurable `lead_window_s`) outweigh signals *during* it;
    signals *after* onset are treated as consequences.
  - **Confidence by noisy-OR** (`1 − Π(1−wᵢ)`) — independent, agreeing evidence
    compounds toward (never reaching) certainty; a lone weak signal stays weak.
  - **Anti-hallucination** — every citation references a real supplied signal;
    thin evidence downgrades to `insufficient_evidence` with a concrete
    `recommended_next_data` list instead of a confident guess.
  - **Advisory / read-only** — proposes a human-approved, MOC-gated, undoable
    next step per cause; executes nothing.
- **`downtime_root_cause_live`** (brain `iaiops/core/brain/rca_collect.py`, MCP
  tool, and `iaiops diag rca-live`) — the copilot that **gathers its own evidence**:
  give it an endpoint + window + refs and it pulls a cross-protocol
  `diagnose_dataflow` probe, a short sampled series per ref (feeding `tag_health`),
  and active OPC-UA conditions, then runs the same advisory analysis. The gathered
  bundle is echoed under `collected_evidence`; reuses only existing read paths, adds
  light read load, and degrades (never raises) on a partial outage.

### Notes
- 68 tools across 9 protocols (7 cross-protocol diagnostics). Still **preview** —
  validated against simulators / mocks, not live equipment.

## 0.4.0 — Industrial-AIOps

First release under the standalone **`industrial-aiops`** org (split out of the
`AIops-tools` IT line). Same governance harness, read-first stance, and preview /
mock-or-sim validation caveat — now a monorepo with a shared core, per-protocol
connectors, a menu-configurable MCP, and a semiconductor/display fab connector.

### Breaking
- **Renamed `ot-aiops` → `iaiops`**: package `ot_aiops`→`iaiops`, CLI/MCP
  `ot-aiops`→`iaiops`, env `OT_AIOPS_*`→`IAIOPS_*`, home `~/.ot-aiops`→`~/.iaiops`.
  Legacy env vars and the legacy home directory are honored as a fallback so
  existing installs keep unlocking secrets / reading audit.
- **Protocol client libraries are now optional extras** — the base package installs
  and imports without them; install only what a site runs:
  `pip install "iaiops[opcua,modbus]"` (or `iaiops[all]`). A call to a
  not-installed protocol returns a teaching error pointing at the right extra.

### Added
- **Shared core** — `iaiops/core/{governance,runtime,brain}`; connectors import it.
- **`IAIOPS_MCP` menu** — expose only the protocols a site runs (named profiles
  `all` / `fab` / `factory` / `process`, or a comma list). `fab` profile = 29 tools
  vs 66 for `all`.
- **SECS/GEM connector** — host-side reads for semiconductor/display fab equipment
  over HSMS (SEMI E5/E30/E37) via the `secsgem` extra: equipment status, SVID/ECID
  namelists + values, alarms, process programs (7 tools).
- **OPC-UA connection self-diagnosis** (`opcua_diagnose_connection`) — classifies a
  failed connect (certificate / security policy / auth / firewall / dns / port /
  config) with the fix; wired into `iaiops doctor`.
- **`subscription_health`** — sequenced-feed loss/reorder/overload (OPC-UA monitored
  items or Sparkplug B): sequence gaps, republish-rejection rate, overloaded channels.
- **Per-industry edition bundles** — `iaiops[fab]` / `iaiops[factory]` / `iaiops[process]`.

### Notes
- 66 tools across 9 protocols. Still **preview** — validated against simulators /
  mocks, not live equipment.
