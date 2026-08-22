# Industrial-AIOps — Roadmap (pending features)

> Backlog of features to add over time. Grouped by priority. Add to this list as
> ideas land; pull items into a release when picked up. (The HLD these slot into is
> an internal design doc, not shipped in this repo.)

## Status — 2026-08-22 (sequencing decided: OEE first, knowledge base second, PdM last)

`readiness` shipped (#166). The next question was no longer "what do we build" but
"in what order" — and a market check on 2026-08-22 changed the answer. Full
evidence with links: [MARKET-EVIDENCE.md](MARKET-EVIDENCE.md); the decisions it
produced: HLD §11–13 (D19–D27).

Three findings drove the ordering:

1. **The knowledge-base loop is already a shipping product category.** Aspen
   Mtell's own description is work orders → failure signatures → monitor for
   recurrence. So it is neither a moat nor an entry ticket — it is a **retention
   mechanism** (D20).
2. **PdM has a 60–70% pilot-stall rate**, and what stalls it is heterogeneity,
   not algorithms. It is the only capability needing BOTH history and labels, so
   it goes last (D19).
3. **OEE has a quantified, demonstrable pain**: manual Excel OEE overstates by
   **8–12 points**, because minor stoppages are too fast for a human to log. It
   needs no feedback loop to prove — just the tap.

And OEE turns out to have the **smallest semantic ask of any capability**:
`run/stop` + `count` + `cycle` — three tags. Downtime RCA needs a full tag list
plus an alarm source plus a historian. The §9 onboarding cliff is narrowest
exactly where the value lands first.

### ⚠️ The blocking finding: nothing collects continuously

An audit on 2026-08-22 found that OEE's *brain* is largely built —
`downtime_events()` segments stops from a state series, `six_big_losses()`,
`oee_multidim()` — while the thing that would feed it does not exist:

| | reality |
|---|---|
| `opcua monitor --duration-s 10` | a BOUNDED window, 10s by default |
| `metrics serve` | only READS the local store; never fills it |
| `~/.iaiops/data.db` | gains rows only when a human runs a read command |

**So "OEE first" is mostly about building continuous collection, not OEE maths.**
That brings disconnect buffering and backfill, retention, crash recovery and
start-on-boot — and it changes the product's shape from "a CLI you run" into
"a thing that runs".

### Open — 1. Continuous collection (the actual first build)

- [x] **`iaiops collect plan` / `collect run`** — shipped. A BOUNDED assessment
      run (`--duration 7d`) that fills the local store, with a hard 14-day cap.
      There is deliberately **no run-forever mode**: that keeps the connectors'
      existing "never an unbounded loop" rule intact, and a run that states when
      it ends is a far smaller change-management ask than a resident daemon —
      which IS the deployment strategy (D21). `collect plan` contacts nothing.
- [x] **A gap is not a stoppage.** A failed read is never written as a value —
      not null, not a stale repeat — because either would be indistinguishable
      from a real sample downstream. Blind windows are reported as data, and the
      run states its coverage (66.67%, not "done"). Conflating the two would
      overstate losses, in the direction that flatters a vendor.
- [x] **The cross-protocol read is now public** (`core/collect/reader.py`). The
      dispatch already existed as `brain.monitor._read_point` over the capability
      registry's `monitor_read`; collection should not import a private name from
      the analysis layer. Collectable today: **opcua, modbus, s7, mc, eip,
      ethernetip** — 6 of 15 registered protocols.
- [x] **`readiness` now answers "can this endpoint be sampled at all"**, and OEE
      depends on it. Protocols without a point-read path are reported as a
      protocol property, not a configuration mistake.
- [ ] Wire `fins` into `monitor_read` — Omron is a conspicuous gap and
      `fins_read_words` / `fins_read_bits` already exist; it is a registration,
      not a build.
- [ ] Retention and store growth: continuous collection turns the local store
      from incidental into something with a lifecycle.
- [ ] Resume/backfill across process restarts (today a stopped run keeps what it
      collected, but a new run starts fresh).

### Open — 2. OEE from configured tags

- [x] **A semantic role on `MonitorTag`** — shipped. `role:` takes one of
      `run_state` / `total_count` / `good_count` / `reject_count`; an unknown
      role fails the config rather than silently becoming "no role", and two tags
      claiming one role is refused (which is the production counter?). Roles are
      **declared, never guessed** (D16/D23).
- [x] **`run_state` requires `running_when`.** The trap this closes: `_is_running`
      treats any non-zero NUMBER as running, which is right for a coil and wrong
      for the status word most PLCs expose — `0=stopped 1=idle 2=running 3=fault`
      would count idle AND fault as productive, inflating Availability and OEE in
      the direction that flatters whoever sells the tool. One extra config line
      removes the whole class of error. `1` and `True` compare equal on purpose:
      a coil reads back as a bool while the author naturally writes `[1]`, and a
      strict match there would silently report zero run time.
- [x] **`ideal_cycle_time_s` on the endpoint** — a product SPEC, not something a
      machine reports, so it is a line value rather than a tag role. OPTIONAL:
      Availability is where minor stoppages live and needs only a run-state tag,
      so the headline gap is reachable before anyone looks up a spec. Without it
      OEE reports Availability (and Quality, given counts) and says so.
      ⚠️ One value per line is the simple case; a multi-product line needs one
      per product.
- [x] **`readiness` OEE went from `blocked` (inexpressible) to a real check.**
      A configured line now reports `degraded` — it can produce a number — rather
      than a dead end.
- [x] **`iaiops oee measure`** — shipped. Availability derived from collected
      history via the line's declared `run_state` tag, with `--reported` for the
      comparison. Pure math in `core/brain/oee_measure.py`; the CLI reads the
      store and renders (the `baseline` / `baseline_store` split).
- [x] **Three buckets, not two.** Time is running / stopped / **unknown**, and
      unknown is never folded into either. Availability is over KNOWN time, with
      coverage reported beside it; below 50% coverage no figure is reported at
      all, because a meaningless number that looks precise is the thing this
      product exists not to produce. Counting a blind window as downtime is the
      TEMPTING error — unexplained downtime inflates the losses a vendor can
      offer to fix.
- [x] **Minor stoppages counted separately** (≤300s default) — the ones a manual
      tally cannot record, and the usual source of the gap.
- [x] **The comparison cannot manufacture a favourable answer**: a refused
      measurement yields no gap, and a measurement ABOVE the reported figure is
      stated as plainly as one below. Hiding the second would make the first
      suspect.
- [ ] Performance and Quality factors from `total_count` / `good_count` +
      `ideal_cycle_time_s` — Availability alone already carries the headline, so
      this completes the figure rather than unlocking it.
- [ ] Wire `six_big_losses()` to the same derived inputs.

**Do not enter as "OEE software"** (D27) — Evocon, Fabrico, Symestic, TEEPTRAK,
MaintMaster and every MES are already there. The difference is the PATH to the
number: `scan` → `readiness` → confirm three tags → real OEE, with no added
hardware and no integrator visit. Those first two steps are already built and
nobody else has them.

### Open — 3. The site knowledge base (retention, not entry)

Design in HLD §12. It must not gate the product's day-one value.

- [ ] The store itself, following `baseline_store` / `alias_store` conventions
      (JSON, 0600, atomic temp+replace, never a device write): structure,
      baselines, cases, weights, signatures.
- [ ] **Every fact tagged `declared` / `derived` / `suggested`** (D23). A
      `suggested` fact used as if `declared` turns RCA confidently wrong, which
      is worse than no answer.
- [ ] **Labels from the audit trail, not from data entry** (D22). `~/.iaiops/
      audit.db` already records what a human changed, when, and who approved it;
      `undo.db` holds the prior state. The fix an engineer applied through the
      tool right after a stoppage IS the label — captured at diagnosis time, in
      our own taxonomy, with the evidence attached. This matters because
      "operators will record the cause" is the single most documented failure
      mode in this category.
- [ ] Human confirmation, where needed, is **one click among the ranked
      hypotheses** — never a free-text field. Dismissing an alert is a negative
      label, and those are free.
- [ ] **Reliability alongside confidence** (D24): 90% from a site with three
      recorded cases is not 90% from a site with three hundred.
- [ ] **Self-confirmation guard** (D25 neighbourhood, HLD §12.10): count a case
      as a label only when a human states the cause independently or overrides
      us, and track the human-agreement rate separately — an unusually high one
      is itself an alarm.
- [ ] Relationships: human-declared line order first. Timestamp co-occurrence
      produces **candidates for confirmation only**, never edges (D25).
- [ ] Line-design/P&ID extraction belongs to the agent front-end and produces a
      PROPOSAL a human confirms (D26) — so the knowledge base never depends on a
      model and the offline app loses nothing.

### Open — 4. PdM (last, and deliberately so)

Needs both accumulated history and labels. Everything above is its prerequisite.

### Open — onboarding (reframed)

`onboard` is not a wizard — it is **the knowledge base's first write**. Doing it
before there is somewhere to put a confirmed mapping would produce a wizard whose
output has nowhere to go, which is why it now follows rather than leads.

---

## Status — 2026-08-19 (unreleased: site discovery + the onboarding gap it exposed)

Two things landed that the earlier status blocks could not have named, because the
first of them did not exist yet.

**Site discovery shipped** (#161 engine, #162 CLI). `iaiops scan` answers the question
that comes *before* every other capability in this product — "what is on this network"
— with no writes, a fixed industrial port allowlist, a zero-emission dry run, and a
self-contained HTML report whose first section is what it touched. Verified through the
command against a real Modbus device.

**Building it exposed a larger gap than it closed.** Every capability before `scan`
assumed you already knew your endpoints; `scan` removes that assumption for the
*device* layer and, in doing so, makes it obvious that nothing removes it for the
*semantic* layer. A new user can now discover 40 devices in an afternoon and still have
no idea which of them matters, which tag is the production counter, or which of the
eleven flagship scenarios they are actually able to run today.

That is not a documentation problem. **"Readiness" was never a first-class concept in
this architecture** — it is now written down as `docs/HLD.md §9`, and the work below is
the part that is still missing.

### Open — onboarding (SUPERSEDED by the 2026-08-22 sequencing above — kept for its detail)

- [x] **`iaiops readiness`** — shipped. A command answering "what can I run right now, and what
      is each blocked capability missing". Doubles as a **maturity baseline**: re-run
      after every site change, and use it to tell a customer what they must invest to
      unlock which scenarios. Report-only: it must NEVER guess a semantic mapping
      (HLD §9.4/D16 — a wrong production-counter mapping produces plausible-looking OEE
      numbers, which is worse than an error).

      Building it surfaced a prerequisite that is not merely unset but
      **inexpressible**: `oee_compute` takes five plain numbers and `MonitorTag`
      carries only a ref, a label and thresholds — there is no field saying "this
      tag is the production counter". The report says so rather than "not
      configured", because the latter sends someone hunting for a setting that
      does not exist. **Adding a semantic role to `MonitorTag` is the unlock for
      OEE-from-configured-tags** and is now the concrete next step.
- [ ] **`iaiops onboard`** — chain the pieces that already exist: `scan` → config draft
      → per-device point-list browse (`opcua/discovery.py`, `eip_list_tags`, Modbus
      templates) → heuristic semantic guess **presented for human confirmation** →
      readiness report.
- [ ] **Both front-ends, one engine** (D17). CLI for engineers on an edge box with no
      GUI and for CI; an App page for the field, because confirming a hundred-row point
      list is a table interaction, not a command-line questionnaire. The engine returns
      structured results; each front-end only renders. CLI covers the point-list step
      with export-CSV → edit → import rather than interactive row-by-row prompting.

### Open — analysis depth (still valid; slots after collection + OEE)

The three flagship directions are **conservative baseline alerting, complete downtime
RCA, and OEE**. Their shared bottleneck is readiness, not algorithms — so this block is
deliberately sequenced *after* the one above. Two are real gaps rather than polish
(HLD §10.3):

- [ ] **Contextual baselines.** `learn_baseline` produces ONE robust band per tag,
      segmented only at the latest operator change. OT normal ranges move with context
      — shift, product/recipe, start-up vs steady state — so one band is either too
      wide to catch a real excursion or too mixed to learn at all. Learn per bucket and
      locate the current context before comparing. Keep the refusal discipline: a
      bucket without enough samples **refuses to learn** rather than falling back to a
      global band, which would disguise "never seen this regime" as "this regime is
      normal".
- [ ] **Relationship-aware correlation** (D18). `_proximity_scale` weights evidence by
      TIME only (cause precedes effect). Without an upstream/downstream axis, one
      upstream stoppage yields a run of equally-confident downstream false root causes.
      Sources ranked by trust: a human-declared line order (enough to start) → SNMP/LLDP
      adjacency (network layer, not process layer) → co-occurrence inference (weakest,
      and readily mistakes correlation for causality).
- [ ] Event-type clustering for alarms — `alarm_bad_actors` groups by source, so ten
      phrasings of one fault count as ten bad actors. Incremental; lowest of the three.
- [ ] **Prerequisites belong in the sales deck.** `ppt/industrial-aiops-介绍-v1.pptx`
      slides 9–20 use a 如何做 → 得到什么 → 价值 → 意义 frame with no 前置条件 row.
      Three of the four evidence classes behind the flagship RCA story need a human or
      a configured historian (HLD §9.2); a demo that omits that will fail on first
      contact with a real site.

### Also now guarded rather than merely claimed

- **The analysis layers cannot reach a language model.** `core/brain`,
  `core/discovery`, `core/runtime` and `connectors` are AST-scanned for any import
  route to a model (`tests/test_brain_is_llm_free.py`, 136 files). This makes
  "the edge app loses nothing without an LLM" a structural property instead of a
  current-state observation — and it is the reason a pure-app front-end and an agent
  front-end are the same engine, not two products.

## Status — 2026-08-02 (current: `iaiops 0.21.1` · `iaiops-energy 0.1.11`)

Latest published: base **`iaiops 0.21.1`**, energy **`iaiops-energy 0.1.11`** — PyPI +
GitHub Release (with the signed Margo package) + MCP registry + SkillHub ×10 + 5 signed
profile images. Energy carries no unreleased commits; its `iaiops>=0.20.3` pin picks up
the current base on a fresh install. Glama re-indexes manually and is the one channel
nothing here can automate.

Since the 2026-07-19 block below: **0.18–0.20.x** (audit on both front-ends via a central
`_govern.py`, effect-based write risk, MCP tool annotations derived from
`@governed_tool`, the NATS 120s hang, `bacnet_write_property`'s unverified `applied`),
then a **verification sweep** across 0.21.0/0.21.1 that cleared every open item on
`docs/VERIFICATION-RECORD.md`'s register and cost **eight product fixes** — among them an
IoTDB reader that returned one tag's values under another tag's name, a TDengine
coverage query that could never have run, an `opcua_diagnose_connection` that leaked a
thread and hung the process, and an RCA pre-incident window that kept each tag's oldest
samples and reported them as complete.

**The statement below that "nothing non-hardware-gated is currently open" was wrong when
it was written, and the sweep is how that was found.** Feature development being
complete is not the same as the features being verified: five protocols and both MCP
transports had never met a real counterparty, and every defect above was invisible to a
green unit suite because the mocks had been written to match the code. The current open
list lives in `docs/VERIFICATION-RECORD.md` — it is short, and it is the honest one.

Still true, and now with more behind it: the remaining value is in **real-device**
verification (rung 3 is zero everywhere, see
[issue #28](https://github.com/industrial-aiops/industrial-aiops/issues/28)) and
ecosystem conformance. Everything that does NOT need hardware is reproducible on a
developer machine — see the container recipes in `VERIFICATION-RECORD.md`.

## Status — 2026-07-19 (historical: `iaiops 0.17.0` · `iaiops-energy 0.1.7`)

Latest published: base **`iaiops 0.17.0`**, energy **`iaiops-energy 0.1.7`** — PyPI +
GitHub Release + MCP registry + SkillHub + 5 signed profile images. Since the 2026-07-13
block below: **0.15.0** (CC-Link tools over master-PLC SLMP, CMMS corpus bridge, timed
A&C, air-gap packaging, signed artifacts), **0.16.0** (eight depth features at zero
tool-surface growth: EtherNet/IP PCCC, MTConnect long-poll streaming, PdM RUL, OEE Six
Big Losses, Sparkplug DataSet/Template, live-verified OPC-UA cert security, RCA causal
graph, ISA-18.2 alarm rationalization), and **0.17.0** (weak/local-model hardening — the
`IAIOPS_NO_EGRESS` registration gate and the return envelope; the `IAIOPS_READ_ONLY` gate
also shipped here but was **removed** in a later release — read/write authorisation is the
caller's decision, and the tap's guarantee is un-bypassable audit on both MCP and CLI; see
CHANGELOG and `docs/HLD.md`).

MCP-registry publishing is now automated from CI via OIDC in both repos
(`.github/workflows/publish-mcp.yml`); the manual `mcp-publisher login` path cannot work
for this org (third-party OAuth app restriction) and its token lived five minutes, which
is why the registry step was skipped in several past releases.

Both items that were open here on 2026-07-19 are now closed:
- ✅ **`iaiops-enterprise`** — both posture gates wired into its own `FastMCP` server and
  the return envelope adopted for `evidence_export`; shipped as `iaiops-enterprise` 0.3.0
  (read-only there now goes 9 → 7). Private wheel, no PyPI.
- ✅ **Doc drift** — the two stacked validation blocks in `README.md` are folded into one,
  anchored at v0.18.0 and grouped by strength of verification.

**Nothing non-hardware-gated is currently open.** Feature development is effectively
complete; the remaining value is in real-device verification and ecosystem conformance,
and both need a field partner rather than more code — see
[issue #28](https://github.com/industrial-aiops/industrial-aiops/issues/28). The
hardware-gated 待核实 list below is unchanged.

## Status — 2026-07-13 (historical: `iaiops 0.14.0` · `iaiops-energy 0.1.5`)

Latest published: base **`iaiops 0.14.0`**, energy **`iaiops-energy 0.1.5`** (PyPI +
GitHub Release + MCP registry). Since the 2026-07-02 block below was written, five
more base releases shipped (0.9.0–0.13.0: FINS / IO-Link / BAS / Ignition read
layers, warehouse / clinical / renewables / plcnext editions, adapter belt, fleet
rollup, PdM + downtime triage, menu-mandatory MCP selection), and IEC-104 gained a
genuine c104 loopback round-trip in `iaiops-energy` (2026-07-13,
`tests/test_iec104_live.py`). The hardware-gated 待核实 list below is unchanged.

## Status — 2026-07-02 (historical; what was actually left then)

Feature development is essentially **complete and published** (base `iaiops 0.8.0`,
energy `iaiops-energy 0.1.2` — PyPI + GitHub Release + MCP registry). Read paths for
Modbus-RTU / BACnet / DNP3 / IEC-61850 are **live-verified** (container simulators;
each found + fixed real connector bugs). What genuinely remains is NOT feature work:

- **Hardware-in-the-loop verification** (needs physical gear, can't be coded): EtherCAT
  (no software simulator — hardware-only), physical RS-485 (Modbus-RTU), live HVAC
  (BACnet write/COV/trend), live HART-IP gateway, live RTU/IED, live PLCnext.
- **信创 hardware**: 国产 OS (麒麟/统信) · 芯 (鲲鹏/海光) · PLC (汇川/台达/信捷) on-target passes.
- **Out of scope (won't do)**: CC-Link *network participation* (but the master-PLC SLMP read
  route is feasible with zero hardware — study: `docs/CCLINK.md`) / PROFIBUS-DP / FL-net;
  IEC-61850 GOOSE/SV; PROFINET RT cyclic.
- **Optional depth**: ~~DNP3 master link-layer status~~ ✅ (energy repo: IMasterApplication
  keep-alive + IIN wired, surfaced by `dnp3_link_status.link_layer`; live 待核实); ~~HART true
  unsolicited burst subscription~~ ✅ (`hart_burst_listen` passive publish listener beside the
  active `hart_burst_sample`; live gateway 待核实); ~~SIEM forwarder auth header~~ ✅ (configurable
  scheme/header env: `IAIOPS_FORWARD_AUTH_SCHEME`/`_HEADER` for Splunk HEC / Elastic ApiKey /
  X-Api-Key). Remaining: OPC-UA FX/TSN (2026 cert watch).

Everything below is the detailed backlog with per-item status.

## Editions / connectors (new verticals)
- 📦 **energy edition — split out to [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)**
  (`pip install iaiops-energy`; depends on `iaiops` core). Removed from this repo; see
  `docs/ENERGY-SPINOUT.md`. History below is retained for context.
- ✅ **energy edition** — shipped in v0.6.0 (read-only monitoring): IEC 60870-5-104
  (`c104`), DNP3 (`pydnp3`), IEC 61850 MMS (`pyiec61850`), with the `energy` MCP
  profile + `iaiops[energy]` bundle. **Binding verification pass (2026-06-30):**
  IEC-104 c104 **symbol/surface pass 2026-06-30** (`tests/test_binding_contracts.py`
  exercises the actual `iec104_session`); a **genuine loopback round-trip first
  passed 2026-07-13** in `iaiops-energy` (`tests/test_iec104_live.py`) — the earlier
  "real c104 loopback" wording here was an overclaim (see
  `docs/PREVIEW-VERIFICATION.md`); IEC-61850 **pin corrected** — the extra
  pointed at the unrelated PyPI `iec61850` (async OOP client, 0 driver symbols); it
  now pins `pyiec61850` (libiec61850 SWIG) and all 14 driver symbols are verified
  present. **Still 待核实:** DNP3 (`pydnp3` ships no wheel + needs a live outstation;
  not yet CI-verifiable) and live-RTU/IED reads. Follow-ups: DNP3 `is_online` live
  link-state via OnStateChange; live-device pass; IEC-61850 GOOSE/SV (out of scope).
  - ✅ **独立仓 spin-out DONE** (internal HLD §3 D4 / §10 P6): moved to the standalone
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
- ❌ Not doing: CC-Link *network roles* (master/slave/device stacks — hardware/cert-gated,
  write-side). ✅ **Shipped instead** (2026-07-15, study + Phase 1 in `docs/CCLINK.md`):
  CC-Link link-device + SB/SW network-diagnostics reads *through the master PLC* via SLMP
  (= MC 3E frame; the existing `mc` connector) — `mc_cclink_templates` /
  `mc_cclink_link_read` / `mc_cclink_network_health` (classic SW0080–; IE Field SB0049 +
  SW00B0– + SW00A0– baton pass; mock-tested, live pass `待核实`). Still not doing:
  PROFIBUS-DP (needs a master card, not software-tappable), FL-net (niche, no library).

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
  guard + thin-history fall-back to defaults). ~~Maintenance-log corpus link~~ ✅
  (2026-07-15, Unreleased): `iaiops/core/brain/maintenance_log.py` +
  `rca_corpus_from_maintenance` MCP tool + `iaiops diag corpus` (CSV/JSON CMMS
  export → `[{cause, signals}]` corpus → weights) — explicit cause → EN/中文
  synonym table → unambiguous keyword inference; ambiguous/unknown rows are
  reported, never guessed. ~~Timestamped alarms from a live A&C event source~~ ✅
  (2026-07-15, Unreleased): `opcua_alarm_events` (bounded A&C event subscription +
  ConditionRefresh; events carry the server's own Time) — `collect_evidence` /
  `downtime_rca_live` now try the timed path first and fall back to the untimed
  address-space scan; verified against a real in-process asyncua server
  (third-party A&C servers `待核实`).
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

## Ecosystem / edge packaging (Margo)
> Positioning + gap in `docs/MARGO-ALIGNMENT.md`. iaiops is a natural **Margo edge application**
> (governed, neutral, air-gap friendly). **NOT Margo-compliant yet** — every row here is `⏳` and
> stays `待核实` until the conformance toolkit passes on real gear. Contributor-first (free); paid
> membership only on customer pull.
- ✅ **Container (OCI) image per edition profile** (2026-07-15) — reproducible, headless MCP
  entrypoint, non-root, read-only-rootfs friendly (`deploy/margo/Dockerfile`). CI
  (`publish-image.yml`) builds multi-arch images per profile on every release tag, **cosign-signs
  them** (public key `deploy/margo/cosign.pub`), and pushes
  `ghcr.io/industrial-aiops/iaiops:<version>-<profile>`. The tag→PyPI race that silently broke the
  v0.12–v0.14 image builds is fixed (CI now waits for the wheel to land on PyPI).
- ✅ **Margo application description — hosted + signed + CI-linted** (2026-07-15) — built to the
  real `margo.org/v1-alpha1` schema (`deploy/margo/margo.yaml`, docs.margo.org PR1 pre-draft).
  CI assembles descriptor + deploy-ready compose into `iaiops-margo-package-<version>.tar.gz`,
  cosign-signs it, and attaches it to the GitHub release (= `packageLocation`; verify key =
  `keyLocation`). `tests/test_margo_package.py` lints descriptor ↔ profile menu ↔ pip extras ↔
  build matrix ↔ version pins. Remaining `待核实` = only the secret-parameter flag
  (margo/specification#145). Then run conformance.
- ✅ **On-box LLM brain option — documented + deployable** (2026-07-15) — `docs/AIRGAP.md` (three
  tiers: deterministic diagnosis needs no LLM at all; `rca_narrate` → on-box Ollama for narration;
  fully local MCP copilot as a documented pattern) + `deploy/airgap/compose.yaml` (signed iaiops
  image + pinned Ollama on an internal-only network, no published LLM ports) +
  `tests/test_airgap_compose.py`. Still `待核实`: a live narration pass against a real Ollama on
  real edge hardware, and any verified local-copilot client/model pairing.
- ⏳ **Margo conformance run** — execute the compliance toolkit on a real device + publish the
  traceable result. **Only after this passes** may any material say *Margo-compliant*.
- ⏳ **Immutable-host validation** — live deploy on a candidate immutable edge OS (IGEL OS or
  equivalent), captured as a `待核实 → verified` row like every hardware pass.

## Packaging / DX
- ✅ **Per-protocol named MCP entry points** (`iaiops-mcp-opcua` … + per-edition
  `iaiops-mcp-fab` / `-energy` / `-building` …) — thin shims over `IAIOPS_MCP`,
  data-driven from the profile menu (`mcp_server/entrypoints.py`); reuse the same
  `server.main`. Sugar; the `IAIOPS_MCP` env already delivers the capability.
- **OPC-UA FX / TSN** roadmap watch (2026 certification) as a future credibility point.

## Standing release debt
- ⚠️ **PyPI token — STILL OPEN as of 2026-07-19.** The same token was re-exposed in chat
  for the 0.7.0 AND 0.8.0 publishes and MUST be revoked; mint a fresh industrial-aiops
  token, keep it in `~/.pypirc` / a secret manager, never paste it into a conversation.
  Releases since then (through 0.17.0) have used the credentials already stored in
  `~/.pypirc` with no token in chat — but if that file still holds the exposed token,
  the exposure is live. Revoking it is the only fix; nothing in this repo can do it.
- ✅ Published all channels: **iaiops 0.21.1** + **iaiops-energy 0.1.11** — PyPI, GitHub
  Releases (with the signed Margo package), the MCP registry
  (`io.github.industrial-aiops/iaiops` + `…/iaiops-energy`, auto-published from CI via
  OIDC on tag), SkillHub ×10, and 5 signed profile images. Glama is manual and is the
  only channel that cannot be automated from here.
- **Release order that works** (learned twice): PyPI first — the image and registry
  workflows both gate on the PyPI simple index — then `gh release create --target main`
  so the release exists before the Margo-package job attaches to it. If one image matrix
  leg fails to resolve the new version, that is a stale PyPI CDN node: `gh run rerun
  <id> --failed` a few minutes later, do not re-cut the version.
