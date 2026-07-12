# Changelog

## Unreleased

### Added — process heat-exchanger fouling + building zone comfort
- **process `heat_exchanger_fouling`** (process_tools) — hot-side temperature effectiveness ε =
  (hot_in − hot_out)/(hot_in − cold_in) per reading, first-half vs second-half; `fouling` when the
  mean is below the floor or it declined beyond the threshold (the signature that precedes a forced
  clean). Cited by the effectiveness numbers.
- **building `zone_comfort`** (building_tools) — occupied-zone comfort + IAQ vs ASHRAE 55 / 62.1
  (temp 20–26 °C, RH 30–60 %, CO₂ ≤ 1000 ppm); per-parameter breach flags, worst-first.

### Added — renewables & plcnext editions + second edition tools (water/fab)
- **New `iaiops-renewables` edition SKILL** (the `renewables` profile had none) + signature tool
  **`pv_performance`** (new `renewables_tools`): flags underperforming PV strings by performance
  ratio vs expected (explicit / nameplate×irradiance) or the fleet median — the soiling/shading/
  failed-string signature. Worst-first, cited.
- **New `iaiops-plcnext` edition SKILL** — a packaging edition documenting PLCnext / vPLC access over
  its built-in OPC-UA (4840) + Modbus process-data server; reuses the OPC-UA/Modbus tools + brain,
  no new connector, no edition tool.
- **water `water_quality_compliance`** (water_tools) — finished-water turbidity / free-chlorine / pH
  vs drinking-water limits (overridable per permit), worst-first, the continuous-compliance companion
  to `disinfection_ct`.
- **fab `defect_pareto`** (fab_tools) — defect-category Pareto with cumulative share and the vital-few
  to the 80 % line, the quality follow-on to `spc_check`.

### Added — water / building / factory edition signature tools (via EDITION_MODULES)
Rounds out every industry edition with its own signature tool, each scoped to its edition module:
- **water `disinfection_ct`** (new `water_tools`) — SWTR disinfection credit: CT = free-chlorine
  residual × T10 contact time per contact basin vs the required CT (supplied from the utility's CT
  table); per-basin ratios worst-first. Does not embed the CT tables.
- **building `economizer_check`** (new `building_tools`) — AHU economizer FDD: simultaneous
  heat/cool, not-economizing (free cooling available but damper at minimum + mechanical cooling on),
  and economizing-when-locked-out; per-AHU faults citing the temperatures/states.
- **factory `changeover_analysis`** (new `factory_tools`) — SMED changeover durations: the gap
  between the last good part of one product and the first of the next; ranks the longest, totals the
  lost time, each cited by its bounding timestamps.

### Added — four edition-scoped signature tools (all via EDITION_MODULES)
Each rides its edition's own tool module — loaded only when that edition is selected, never the
always-on brain — the mechanism working across four verticals:
- **warehouse `sortation_health`** (`warehouse_tools`) — sorter read-rate / no-read / mis-sort
  analysis over per-divert records; ranks the worst chutes; every rate cited by counts.
- **clinical `or_environment_check`** (`clinical_tools`) — operating-room ventilation vs ASHRAE 170
  Table 7.1 (temp 20–24 °C, RH 20–60 %, ≥20 ACH); per-parameter breach flags, worst-first.
- **process `control_loop_health`** (new `process_tools`) — PID loop triage from a PV/SP/OP capture:
  oscillation (error-crossing rate), sustained offset, output saturation → worst-wins verdict.
- **fab `spc_check`** (new `fab_tools`) — SPC control-chart rules (Western Electric 1–4 + a 6-point
  Nelson trend) over a measurement series, each violation cited by point index; Cp/Cpk with spec limits.

### Added — line_bottleneck (warehouse edition tool, first EDITION_MODULES user)
- **`iaiops/core/brain/throughput.py`** + governed MCP tool **`line_bottleneck`** (in a new
  `warehouse_tools` **edition module** attached to the `warehouse` edition): Theory-of-Constraints
  over per-station throughput / cycle-time data — the slowest station is the line's constraint and
  sets the line rate; starvation/blocking corroborate (upstream blocks, downstream starves). Ranks
  the line, names the constraint + co-constraints within a %, tags each station starved/blocked,
  cites the number. Pure, read-only, advisory. Loads ONLY for `IAIOPS_MCP=warehouse` — the first
  tool to use the new per-edition mechanism instead of the always-on brain.

### Changed — per-edition tool modules + raised tool-flood threshold (architecture)
- **`EDITION_MODULES`** — a named edition can now carry its own `@mcp.tool` group beyond its
  protocols and the always-on brain. These modules load ONLY when that edition is selected (never a
  bare protocol key, never the global brain), so edition-specific tools no longer have to be
  smuggled into a protocol module or inflate the always-on surface. `selected_tool_modules` /
  `selected_editions` wire it; `selection_tool_count` and the skill-sync surface check use the same
  single source of truth.
- **`clinical_tools`** — `isolation_room_check` + `medical_gas_check` moved out of `bacnet_tools`
  into a dedicated edition module attached to the `building` and `clinical` editions. A raw
  `IAIOPS_MCP=bacnet` selection no longer pulls them (correct scoping); building/clinical still do.
- **`TOOL_FLOOD_WARN_THRESHOLD` 60 → 100** — the always-on brain (~49) plus a full edition's
  protocols + edition modules legitimately reaches ~60-85 (building ≈ 83), so 60 fired on normal
  editions. 100 sits above any single intended edition while still flagging `IAIOPS_MCP=all`
  (~140 tools) — the case the warning is meant to catch.

### Added — clinical-facility edition (医疗设施) + medical-gas safety check
- **New `clinical` profile + `skills/iaiops-clinical/SKILL.md` edition** — promotes the healthcare
  slice out of `iaiops-building` into its own vertical (hospital facilities: different buyer /
  NFPA 99 & infection-control compliance than generic building management). Protocols: BACnet
  (BMS) + Modbus (gas alarm panels / meters) + OPC-UA (SCADA); reuses the building/BACnet tools and
  brain. New `iaiops-mcp-clinical` entrypoint.
- **`medical_gas_check`** (in `clinical_facility` / `bacnet_tools`, alongside `isolation_room_check`):
  grades medical-gas / vacuum source pressures against NFPA 99 / HTM 02-01 — positive-pressure gases
  (O2 / medical air / N2O / nitrogen / CO2) must sit in ~345–380 kPa; medical vacuum / WAGD must be
  deep enough — into normal / low_pressure / high_pressure / insufficient_vacuum / critical,
  worst-first, citing the number. Pure, read-only, advisory (the station's NFPA 99 alarm panel
  remains source of truth).

### Added — warehouse / intralogistics edition (仓储/物料搬运)
- **New `warehouse` profile + `skills/iaiops-warehouse/SKILL.md` edition** for distribution
  centers / material handling: EtherNet/IP (Rockwell conveyor & sorter PLCs) + Profinet (Siemens
  lines) + Modbus (VFD/meters) + OPC-UA (WMS/WCS gateways) + MQTT-Sparkplug (AGV/AMR & IoT), plus
  the cross-protocol brain. A packaging edition — reuses `pdm_forecast` (conveyor-drive bearing/
  thermal trend), `downtime_triage`, OEE and alarm analysis as-is (no new global-brain tool).
- **Two material-handling Modbus templates** (`conveyor_vfd`, `agv_battery`) — placeholder register
  maps (待核实, vendor-specific) whose drive_temperature / motor_current / state_of_charge feed
  `pdm_forecast`. New `iaiops-mcp-warehouse` console entrypoint.

### Added — clinical-facility safety: isolation-room pressurization (building edition)
- **`iaiops/core/brain/clinical_facility.py`** + governed MCP tool **`isolation_room_check`**
  (in `bacnet_tools`, so it is scoped to the `iaiops-building` / BACnet edition — NOT the always-on
  global brain, keeping single-protocol sites under the tool-flood target): the healthcare slice
  generic BMS lacks. Grades each isolation room's differential pressure against ASHRAE 170 / CDC — airborne-
  infection isolation (AII) must stay **negative**, protective-environment (PE) **positive**, at a
  minimum ~2.5 Pa — into `reversed` (wrong polarity, a reportable patient-safety event), `breach`
  (right polarity but too weak), `low_margin`, or `compliant`, worst-first, citing the number behind
  every flag. Pure analysis over differential-pressure readings (from `bacnet_read_points` AI points
  or a historian); read-only and advisory. First step toward an `iaiops-clinical` edition if the
  hospital-facility vertical warrants its own routing identity.

### Added — legacy-PLC visibility profile (what am I inheriting?)
- **`iaiops/core/brain/plc_visibility.py`** + governed MCP tool **`plc_program_visibility`**
  (`plc_program_tools`): a maintainability/operational-risk read one level above the structural
  outline — folds a parsed EXPORTED program (SCL/ST/AWL/L5X) into documentation coverage +
  least-commented blocks, **unreferenced blocks** (possible dead code, flagged honestly — could be
  an entry/task routine or an unresolved call), **complexity hotspots**, **risky constructs**
  (unconditional JMPs, retentive RTO timers, loops), and a **transparent additive risk score**
  whose every point cites its reason. Structural only, cite-first (source_file + line / rung),
  read-only; reuses `plc_program` — no new live-PLC access.

### Added — downtime triage copilot (composes the three downtime lenses)
- **`iaiops/core/brain/downtime_copilot.py`** + governed MCP tool **`downtime_triage`**
  (`downtime_tools`, always-on brain): one call that composes **`alarm_cascade`** (which alarm to
  look at first), **`downtime_root_cause`** (the cited causal verdict), and **`pdm_forecast`** (which
  signals were degrading *before* the trip) over a single incident. Adds a **cross-check**: is the
  first-out alarm actually cited by the RCA's primary cause (`corroborated`) or does the verdict lean
  elsewhere (`diverging`)? Pure composition — every field traces to a sub-report echoed for
  drill-down; read-only, advisory, thin-evidence-honest. Answers the operator's three simultaneous
  questions on a stopped line in one shot.

### Added — alarm-cascade collapse (first-out root)
- **`alarm_cascade`** brain fn + governed MCP tool (`alarm_flood` / `alarm_tools`): collapses an
  alarm flood into cascades — a new cascade starts after a quiet gap > `window_s` — and reports each
  cascade's **first-out** alarm (earliest annunciation) as the likely root, plus downstream members
  and chattering sources. Answers "which alarm to look at first" in a 100+/10-min flood. First-out is
  a transparent, timestamp-cited heuristic (NOT causal — that's `downtime_root_cause`); read-only,
  pure over provided events, or live via the OPC-UA active-condition scan. Complements
  `alarm_flood_analysis` (the "how bad") with the "what's the root".

### Added — predictive maintenance (trend + time-to-threshold)
- **`iaiops/core/brain/pdm.py`** + governed MCP tool **`pdm_forecast`** (`pdm_tools`, always-on brain):
  the predictive step above `baseline_check` (which flags an *already-happened* violation). From a
  value's recent history it fits a robust **Theil–Sen** trend (median of pairwise slopes — no ML,
  outlier-resistant) and, if the trend continues, estimates the **ETA to the nearest warn/alarm
  limit** in the direction of travel → status `insufficient_data | stable | degrading | imminent`.
  Refuses thin history (< 30 samples); cited (window / slope / current / limit / ETA); read-only,
  pure over the provided series. Reused across renewables / warehouse / manufacturing PdM.

## 0.11.0 — 2026-07-12

> Big feature batch from the IGEL/OT field work: an **adapter belt** (InfluxDB sink · NATS egress ·
> on-box Ollama), governed **MCP tools** for it, an **HTTP/SSE transport + account/IP allowlist**
> (gateway-frontable), a **fleet / multi-site** rollup, a **renewables (solar/wind)** edition + PdM,
> a real **Margo `v1-alpha1`** app descriptor, **IGEL** submission readiness, and **GHCR** image
> publishing. Docs/packaging + additive features; no breaking API changes. (Deprecated brain aliases
> `health_summary` / `anomaly_scan` remain — now scheduled for removal in 0.12.)

### Added — adapter belt (lightweight core, open to every interface)
- **Formalized the `ingress → core → egress` architecture** (`docs/ADAPTERS.md`): the core binds no
  store/bus/host/model; every integration is an optional, lazily-imported adapter behind a tiny SPI.
- **`influxdb` historian sink** (`iaiops.core.sink.influxdb`, extra `iaiops[influxdb]`) — InfluxDB
  v1/v2 via line protocol over HTTP (reuses the `requests` pin; no heavy SDK). Registered in
  `get_sink` / `SUPPORTED_SINKS`.
- **Stream egress SPI + NATS publisher** (`iaiops.core.egress`, extra `iaiops[nats]`) — publish
  normalized points + RCA/alarm events to a bus (`publish_points` / `publish_event`). Read-first safe
  (egress of iaiops' own reads/findings, never a control write).
- **On-box local-LLM SPI + Ollama provider** (`iaiops.core.llm`, extra `iaiops[ollama]`) — fully
  air-gapped **narration of an already-cited RCA verdict**; strict cited-only prompt, never derives
  causes (`docs/RCA.md`).
- **Governed MCP tools for the belt** (always-on brain modules `egress_tools` / `llm_tools`):
  `stream_publish` / `stream_publish_event` (publish reads/findings to NATS) and `rca_narrate`
  (on-box LLM narration) — all `[READ][risk=low]`, so an agent can drive egress + narration directly.
- **`docs/RCA.md`** — explains the deterministic, cited, anti-hallucination RCA core ("not a black
  box"); **`docs/FOOTPRINT.md`** — small-by-design footprint + measurement recipe.
- All three adapters are mock-tested (no live server/model needed) and marked `待核实` against real
  backends.

### Added — renewables (solar/wind) edition + PdM
- New **`renewables`** edition (光伏/风电): `IAIOPS_MCP=renewables` / `iaiops-mcp-renewables` /
  `pip install iaiops[renewables]` (modbus + opcua + sparkplug). Device-level monitoring of **PV
  inverters** (reusing the existing SUN2000 / Growatt Modbus templates) + a new
  **`generic_wind_turbine`** template + plant SCADA, with **predictive/preventive maintenance** via
  the existing baseline + RCA brain. Solar/wind **semantic classes** added (irradiance, wind_speed,
  rotor_speed, pitch_angle, yaw_angle, state_of_charge) — placed first so they aren't shadowed by
  greedy generic hints. Grid/substation telecontrol (IEC-104/DNP3/61850) stays in `iaiops-energy`.

### Added — fleet / multi-site rollup (central view over many edge sites)
- **`iaiops/core/brain/fleet.py`** + governed MCP tools **`fleet_status`** / **`fleet_incidents`**
  (`egress`-adjacent always-on brain module `fleet_tools`): the tier above
  `data_quality_fleet_rollup` (per-endpoint, one site) — aggregate per-site status reports across a
  whole **fleet of edge sites** (health status, offline-by-staleness, worst-sites-first, fleet score)
  and roll up active RCA incidents into fleet-wide top causes. Read-only, pure over provided reports;
  a central collector gathers them via a shared historian or each site's HTTP/SSE MCP. Matches the
  IGEL-UMS "centrally manage a large fleet of edge sites" story.

### Added — HTTP/SSE MCP transport + account/IP allowlist (gateway-frontable)
- The MCP server can now run over **HTTP/SSE** instead of only stdio, so it can sit **behind a
  gateway** (e.g. a FastAPI front): `IAIOPS_MCP_TRANSPORT=stdio` (default) `| sse | streamable-http`
  (alias `http`), with `IAIOPS_MCP_HOST` / `IAIOPS_MCP_PORT` (`mcp_server/transport.py`).
- **Account/IP allowlist** (`iaiops/core/governance/allowlist.py`, env `IAIOPS_ALLOWLIST_ACCOUNTS` /
  `IAIOPS_ALLOWLIST_IPS`, CIDR-aware) — defense-in-depth for the standalone HTTP case (an ASGI
  middleware 403s non-allowlisted client IPs) and a reusable check for a fronting gateway. stdio is
  unchanged; a non-loopback bind with no allowlist logs a warning. Answers the recurring Margo/IGEL
  "stdio vs HTTP transport" question.

### Added — OCI image publishing (GHCR)
- `.github/workflows/publish-image.yml` — on a `vX.Y.Z` tag (or manual dispatch) builds + pushes the
  hardened image (`deploy/margo/Dockerfile`) **per edition profile, multi-arch (amd64/arm64)** to
  `ghcr.io/industrial-aiops/iaiops:<version>-<profile>` (factory also tagged `<version>` + `latest`).
  Installs the published PyPI wheel — publish to PyPI first, then tag. No local Docker needed. This
  unblocks IGEL Managed-Container deploys and a working IGEL-Community recipe.

### Changed — IGEL App Portal submission readiness (`deploy/igel`)
- `deploy/igel/README.md` documents the **IGEL Ready** path (private App Creator vs certified App
  Portal) + the Guided App Submission workflow (acceptance → security review → publishing) and its
  requirements. Recommends the **Managed Container (OCI)** route to sidestep the debian/ubuntu-only
  dependency constraint (a pip/Python app is awkward as a native recipe).
- `app-recipe/`: `app.json` bumped to 0.10.1 with the `public_version`-absent submission rule; added
  `igel/thirdparty.json` (binary manifest). Version refs across `deploy/` aligned to 0.10.1.

### Changed — Margo app descriptor rebuilt to the real spec
- `deploy/margo/margo-application.yaml` → **`deploy/margo/margo.yaml`** (spec-canonical filename),
  rewritten to the actual **`margo.org/v1-alpha1` ApplicationDescription** schema (docs.margo.org,
  PR1 pre-draft): real `deploymentProfiles` (compose) / `components` / `requiredResources` /
  `parameters` (env-var targets) / `configuration` + validation `schema`. The `待核实` markers now
  cover only genuine gaps — the hosted+signed package location/key, and the missing secret-parameter
  flag (our open app-package-definition-wg question). Still not conformance-tested → not compliant.

## 0.10.1 — 2026-07-10

> Docs + packaging only — **no functional/source code change** vs 0.10.0 (hence a patch).
> Also folds in doc refreshes: FINS CLI examples, READMEs to 0.10.0 (14 protocols / 132 tools).

### Added — edge-native / Margo ecosystem alignment (docs + packaging skeleton)
- **`docs/MARGO-ALIGNMENT.md`** — positions iaiops as a [Margo](https://margo.org/) **edge
  application** (device / orchestration / application role map), with an honest gap analysis, a
  contributor-first participation plan, verified join steps, and ready-to-paste WG posts.
- **`deploy/margo/`** — container + application-description **skeleton**: `Dockerfile` (non-root,
  read-only-rootfs friendly, headless `iaiops-mcp`, build-arg `PROFILE`), `compose.yaml` (hardened:
  `cap_drop: ALL`, no-new-privileges, no inbound ports, single state volume), `margo-application.yaml`
  (app-description skeleton — every unconfirmed field marked `待核实`), and a README.
- **`deploy/igel/`** — IGEL OS 12 **distribution overlay** (one candidate host; core image stays the
  neutral `deploy/margo/` one): Managed-Container route (reuse the OCI image) + an `igelpkg`
  app-recipe skeleton (`app.json` / `igel/install.sh` / systemd unit), all IGEL-specific specifics
  marked `待核实`. IGEL is referenced ONLY inside this overlay (brand-isolation rule).
- **Positioning** — README (EN + zh-CN) gain an *edge-native / Margo* deployment subsection;
  `pyproject.toml` keywords add `edge` / `iiot` / `edge-computing` / `margo` / `edge-interoperability`;
  `docs/ROADMAP.md` gains an "Ecosystem / edge packaging (Margo)" section.
- **Honesty note:** iaiops is **NOT Margo-compliant** yet — a built/pushed image, a real app-package
  descriptor, and a passing conformance-toolkit result are all roadmap `⏳`. No material claims
  compliance until that published result exists.

## 0.10.0 — 2026-07-02

### Changed — session factory refactor (B1)
- `iaiops/core/runtime/connection.py` (982 lines) refactored: the shared guard → build →
  connect/translate → yield → teardown-swallow lifecycle is now a single generic
  `make_session()` factory in `iaiops/core/runtime/session_factory.py` (exported from
  `iaiops.core.runtime` for downstream packages, e.g. iaiops-energy); each protocol's
  `_build_*`/`_translate_*` moved into its connector (`iaiops/connectors/<proto>/transport.py`),
  with `connection.py` reduced to a thin assembly module keeping the exact same public API,
  semantics, and test monkeypatch points (`connection._build_<proto>_*`). Zero behavior change.
### Added — conservative baseline learning (A6)
- **Change-log baseline — explicitly NOT black-box anomaly detection** (MARKET-INSIGHTS R6:
  zero false positives or it is noise). New brain modules `iaiops.core.brain.baseline`
  (pure: robust p1/p99 + median/MAD band, no ML deps) and `baseline_store`
  (`~/.iaiops/baselines.json`, owner-only 0600, atomic writes).
- Learning **refuses thin history** (< 100 usable samples or < 24h span) with an explicit
  `insufficient_data` verdict listing exactly what is missing; operator changes recorded via
  the change log restart learning at the latest change point (the band never mixes regimes).
- Checking is **silent by default**: violations only beyond p1/p99 by > 3×MAD AND sustained
  ≥ 3 consecutive samples (single spikes never flagged); every violation cites the baseline
  window (from/to ts, n samples), the band values, and the offending samples' ts/values.
- New governed MCP tools (all `[READ][risk=low]`, always exposed with the brain):
  `baseline_learn` / `baseline_check` / `baseline_record_change` / `baseline_status`
  (`no_baseline` / `learning` / `ok` / `violation` — never guesses; bounded outputs).
- New CLI: `iaiops baseline learn|check|change|status` over the local SQLite history.
### Added — historian read integration (A7)
- **Historian readers** (`iaiops/core/sink/reader.py`): a `HistorianReader` protocol +
  `get_reader()` registry mirroring `get_sink()`, with `sqlite` (delegates to the existing
  local query layer), `tdengine`, and `iotdb` readers querying the SAME layout their sinks
  write. Same lazy optional extras as the sinks (`iaiops[tdengine]` / `iaiops[iotdb]`) with
  teaching errors; validated ISO time bounds, capped limits, parameterized/neutralized queries.
- **RCA pre-incident evidence**: an optional per-site `historian:` config block
  (`reader: sqlite|tdengine|iotdb`, password via the encrypted secret store) lets
  `downtime_root_cause` / `downtime_root_cause_live` pull the 2h pre-incident window
  (`iaiops/core/brain/rca_history.py`) and score tag trends as one more evidence class —
  citations name the source (`historian:<name>`), window, and sample count. Strictly
  additive: without the config, RCA output is byte-identical (test-proven).
- **Governed MCP tools** (always-on brain module `historian_tools`): `historian_query`
  (bounded rows + truncation flag) and `historian_coverage` (per-tag row counts +
  first/last timestamps — "what history do we actually have"), both `[READ][risk=low]`.
- **CLI**: `iaiops historian query` / `iaiops historian coverage` alongside the existing
  `historian push`.
- Edition skills (fab/factory/process/building/water) document the two new brain tools.
### Added — legacy PLC program explainer (A8)
- New brain package `iaiops/core/brain/plc_program/`: structural extraction over
  **exported** program text files (Siemens SCL/ST `.scl`/`.st`, AWL/STL `.awl`,
  Rockwell Studio 5000 `.L5X`) — never a live PLC upload. Every extracted element
  carries `source_file` + `line` (rung number for L5X ladder) so the explaining
  agent must cite real locations. L5X is parsed with stdlib `xml.etree` plus a
  pre-parse DTD/entity rejection (XXE hardening); malformed/truncated files
  degrade to `parse_errors` entries instead of crashing.
- 3 governed READ tools (always-on brain module `plc_program_tools`):
  `plc_program_outline` (blocks / VAR sections / IF-CASE branches /
  timers-counters / call graph, bounded with truncation flags),
  `plc_program_xref` (every read/write/call/declare site of a symbol or absolute
  address with the source line quoted), `plc_program_section` (one named block's
  source text, ≤200 lines). Path validation: file must exist, ≤5 MB,
  extension allowlist, no directory walking.
- CLI: `iaiops program outline|xref|section`.
- All 5 edition skills document the 3 tools under 跨协议脑.
### Changed — explicit tool menu by default + brain-only server (B2/B3) **BREAKING**
- **No default tool selection**: a bare `iaiops-mcp` (no `IAIOPS_MCP` env) no longer
  silently exposes the full 100+ tool surface — it prints the selection menu (named
  profiles + protocol keys + per-selection tool counts + examples) to stderr and exits 2.
  `IAIOPS_MCP=menu` prints the same menu explicitly; `IAIOPS_MCP=all` still works as an
  explicit power-user opt-in (a tool-flood warning is logged above 60 tools).
- **Brain-only server (B3)**: new named selection `IAIOPS_MCP=brain` (cross-protocol
  brain, zero protocols) + `iaiops-mcp-brain` console script; new `IAIOPS_MCP_NO_BRAIN=1`
  toggle registers protocol selections *without* the brain modules, so multi-process
  sites run 1 brain MCP + N brain-less protocol MCPs with no duplicate tool names.
  The `protocols_supported` discovery tool stays exposed even under NO_BRAIN.
- **Migration**: set `IAIOPS_MCP=<selection>` (comma list of protocols and/or a named
  profile) or launch a pre-scoped `iaiops-mcp-<name>` entrypoint; to restore the old
  behavior exactly, set `IAIOPS_MCP=all` explicitly.

### Added — Omron FINS connector (A5)
- **Omron FINS** (backlog A5, APAC/华南 install base): new `fins` protocol —
  in-repo **stdlib-only** FINS client (`iaiops/connectors/fins/client.py`, no
  third-party dependency): 10-byte FINS header framing, FINS/UDP (default port
  9600) + FINS/TCP (node-address handshake per W342), SID matching (mismatch
  rejected, retries=0), bounded response parsing, end-code table per Omron
  W227/W342. Commands: 0101 memory-area read (words/bits, DM/CIO/W/H/A/EM),
  0102 memory-area write, 0501 controller data read, 0601 controller status.
- MCP tools `fins_cpu_info` / `fins_cpu_status` / `fins_read_words` /
  `fins_read_bits` / `fins_read_many` [READ, risk=low] + `fins_write_words`
  [WRITE, risk=HIGH, MOC: dry-run default, BEFORE-value capture, undo
  descriptor]; CLI `iaiops fins cpu|status|words|bits|write-words`
  (double-confirm on `--apply`); `fins_session` via the B1 session factory;
  `IAIOPS_MCP=fins` menu entry + `iaiops-mcp-fins` entrypoint; added to the
  `factory` profile/extra (`fins = []` extra — stdlib, pins nothing).
- Self-test: in-repo mock FINS UDP/TCP responder (tests/test_fins.py). Live
  Omron PLC behaviour and banked-EM access remain 待核实.

### Added — IO-Link connector (A10)
- **IO-Link connector** (`iaiops/connectors/iolink/`, read-only v1): sensor-level visibility via
  the IO-Link master's HTTP/JSON interface (IO-Link consortium "JSON Integration"). Both dialects
  selectable per endpoint via `flavor:` — `iotcore` (ifm IoT-Core POST envelope, default) and
  `rest` (plain-REST GET, Balluff/Turck-style). Reads: master identity (`/deviceinfo/...`),
  bounded ≤32-port sweep (mode/status + connected-device identity), per-port device identity,
  process-data-in (raw hex + byte array), ISDU acyclic parameter read (`iolreadacyclic`). NO
  write tools. Bounded/size-capped HTTP (response cap 256 KiB, timeout from `timeout_s`), JSON
  schema-checked with teaching errors. Reuses the MTConnect HTTP pin (`iaiops[iolink]` →
  `requests`); no new hard deps.
- 6 governed MCP tools (all [READ][risk=low]): `iolink_master_info`, `iolink_ports`,
  `iolink_device_info`, `iolink_read_pdin`, `iolink_read_isdu`, `iolink_scan`; registered in the
  `factory` and `building` profiles + `iaiops-mcp-iolink` entrypoint; CLI `iaiops iolink
  master|ports|device|pdin|isdu|scan`; doctor probe + init wizard support.
- Self-test: in-process mock IO-Link master (both flavors) in `tests/test_iolink.py`
  (identity/ports/pdin/isdu round-trips, size cap, malformed JSON, flavor switching,
  governance markers). Live master datapoint paths 待核实.
### Changed — brain/opcua tool split, flagship function refactor, tool-signature polish (B4/B5/B7)
- **B4 — DEPRECATED: `health_summary` / `anomaly_scan`** are OPC-UA-specific and moved out of
  the always-on brain into the opcua protocol module as **`opcua_health_summary` /
  `opcua_anomaly_scan`**. The old names remain registered in the brain for ONE release as
  deprecated aliases: they delegate to the same implementation and their response gains
  `"deprecated": "renamed to opcua_health_summary; this alias is removed in 0.11"`
  (respectively `opcua_anomaly_scan`). **Both aliases are removed in 0.11** — switch to the
  `opcua_*` names. Edition skills updated (new names in the OPC-UA section; old names marked
  deprecated in the 跨协议脑 line).
- **B5 — flagship brain function split (pure refactor, zero behavior change)**:
  `diagnostics.py` `subscription_health` / `diagnose_dataflow` and `rca.py` `downtime_rca` /
  `_score_alarms` decomposed into `_collect_*` / `_score_*` / `_render_*` helpers so each
  public function is <50 lines of orchestration; worst nesting in
  `iaiops/core/governance/patterns.py` (`PatternEngine._load` / `match`) flattened via
  early-continues and an extracted `_evaluate_armable`.
- **B7 — tool-signature polish**: all MCP tool parameters now use parameterized generics
  (`list[str]`, `dict[str, float]`, … — no bare `list`/`dict`, so the LLM-facing JSON schema
  carries element types); docstring risk tags unified — every read tool's first line starts
  `[READ][risk=low]`, writes keep `[WRITE][risk=HIGH][MOC]`. Enforced by the new
  `tests/test_tool_annotations.py` walking every registered tool.

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
