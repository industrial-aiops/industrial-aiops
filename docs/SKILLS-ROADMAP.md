# iaiops skill roadmap — OT / edge, global market

> Product-level roadmap (distinct from `ROADMAP.md`, which is the feature backlog). Distilled from
> the IGEL/OT field work and industry research. **Scope split:** OT / edge / industrial → **this repo
> (`iaiops`)**; IT / endpoint / VDI → the **`AIops-tools`** org. Both ship as **IGEL App Portal
> containers** — the "IT/OT combo": IGEL governs access (AI Armor / UMS), iaiops brings OT intelligence.
>
> **Market: global, English-first, bound to international standards** (IEC 62443 / NIST 800-82 / ISA-18.2).
> China OT is domestic-first (state control of energy) — the only wedge is "energy going global"
> (Chinese wind/solar EPCs building plants in Europe / the Americas / the Far East).

## Skills (task → purpose → value → reuse / priority)

| Skill | Purpose | Value (global pain) | Reuse / new · Priority |
|-------|---------|---------------------|------------------------|
| **ot-downtime-copilot** | Cross-protocol RCA + on-box LLM narrating "upstream drift → downstream stop" | ~$1T/yr downtime; **MTTR 49→81 min** (skills gap) — cut diagnosis time | reuse rca/fleet/ollama · **P1** |
| **renewables-pdm** (deepen the shipped `renewables` edition) | Inverter / wind-turbine edge PdM; 6–12 mo bearing lead time | wind O&M is **55–65% of OPEX**; offshore $65–85k/MW/yr; ties to "energy going global" | reuse renewables+baseline · **P1** |
| **legacy-plc-visibility** | Bridge pre-2005 PLCs (Modbus / S7 / PROFINET) with no OPC-UA into the normalized model | **protocol fragmentation = the #1 IIoT project killer**; no rip-and-replace | reuse connectors · P2 |
| **substation-intel** (`iaiops-energy`) | Multi-vendor IED normalization + alarm-flood convergence (IEC-104 / DNP3 / 61850) | SCADA floods (100+ alarms/10 min); multi-vendor IEDs don't interoperate | reuse energy+alarm · P2 |
| **airgapped-diagnosis** (cross-cutting; package as a selling point) | On-box LLM + read-first tap; keep diagnosis alive with no WAN / across an air gap | energy/water/transport enforce hard OT/IT separation — **the real differentiator vs cloud AIOps** | mostly shipped (ollama+allowlist) — doc/package · P2 |
| **warehouse-pdm + dc-fleet** (logistics) | Conveyor / AGV edge PdM + cross-DC fleet rollup | AGV telemetry signatures 48–96 h pre-failure; cascading conveyor stops; no cross-site view | reuse pdm+fleet · P3 |
| **clinical-facility-iot** (healthcare OT slice) | OR/ICU HVAC, O2, UPS, cold-chain over BACnet + on-box LLM (HIPAA-safe, data stays on-site, read-first) | differentiated but a narrow market | reuse bacnet+brain+ollama · P3 |

## Cross-cutting design invariants (all skills)
1. **Distributed sites → fleet rollup** (universal, unmet across wind farms / substations / plants / DCs).
2. **Protocol fragmentation → the governed read-only tap** is the wedge.
3. **Alarm floods / threshold blindness / bad tags → explainable multivariate anomaly detection + RCA**,
   with **false-positive discipline as a hard requirement** (one wrong "critical" and operators stop trusting it).
4. **Air-gap / skills-shortage / tribal-knowledge loss → on-box LLM diagnosis, read-first, dry-run-on-write** —
   this is the differentiator, not a nice-to-have.

## Adoption strategy — free & open first
**No monetization for now — the goal is a user base, not revenue.** Everything stays **free and MIT
open-source**; the priority is real-world adoption, verified-equipment coverage, and reference
deployments. **Welcome customization, contributions, and collaboration** — issues/PRs, custom
connectors/editions, and co-development with partners and design partners.

Pricing is **deliberately deferred** — revisit only once there's genuine adoption/pull. Possible
models (open-core, per-edge-node/site subscription, an optional hosted fleet console) are parked for
later and **not decided now**. (Note for whenever we do: per-call/usage metering is a poor fit for
air-gapped/on-box-LLM OT — charge for capability, not tokens.)

## Regional expansion — Japan (protocol coverage)
Japanese factories are Mitsubishi / Omron / Yokogawa heavy. iaiops already covers the big slice; the
notable gaps are hardware-gated (like EtherCAT/PROFINET), so coverage is honest, not universal.

| Japan-relevant protocol | Status in iaiops | Note |
|-------------------------|------------------|------|
| **Mitsubishi MC / MELSEC (SLMP)** | ✅ covered (`mc`) | SLMP is MC's successor — MC frame covers most reads |
| **Omron FINS** (CS/CJ/CP/NX) | ✅ covered (`fins`) | APAC/Japan Omron installed base |
| **SECS/GEM (HSMS)** | ✅ covered (`secsgem`) | semiconductor/display fabs — huge in Japan |
| **Modbus / OPC-UA / MQTT-Sparkplug** | ✅ covered | global, present in Japan too |
| **CC-Link / CC-Link IE (TSN)** | ❌ not covered | **the biggest Japan gap** — but a fieldbus needing a master card / hard-real-time NIC (same reason EtherCAT/PROFINET are hardware-gated); CC-Link IE TSN is more tappable but a large build. `待核实` feasibility |
| **FL-net (OPCN-2, JEMA)** | ❌ not covered | niche Japanese FA Ethernet; low priority |
| **Yokogawa Vnet/IP** (Centum DCS) | ❌ not covered | Yokogawa DCS backbone; niche, proprietary |

**Read:** MC + FINS + SECS-GEM already give strong Japanese electronics/semiconductor/discrete-mfg
coverage. **CC-Link IE TSN** is the one worth evaluating for a real Japan push (Mitsubishi ecosystem
dominance) — but it's a hardware-gated, non-trivial connector; scope it only with a Japanese design
partner. Everything else (FL-net / Vnet-IP) is niche.
