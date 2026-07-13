# 能源 edition 独立仓 — 抽仓计划 (spin-out plan)

> **Status: DONE — energy edition split out.** The connectors, session builders, MCP
> tools, and tests moved to **[industrial-aiops-energy](https://github.com/industrial-aiops/industrial-aiops-energy)**
> (`pip install iaiops-energy`), which depends on `iaiops` for the shared core. They
> were removed from this base repo (this PR); both repos stay green. This doc records
> the plan that was followed (per the internal HLD §3 D4 / §10 P6 — a design doc not
> shipped in this repo).

## Why split

- **Different buyer / domain** — utilities & substations (遥测/遥信, IEC-104 / DNP3 /
  IEC-61850) vs. the factory/process/fab core; separate sales, compliance (电力监控
  系统安全防护规定), and release cadence.
- **Heavier, platform-specific deps** — `pyiec61850` is a linux-only SWIG wheel,
  `pydnp3` ships no wheel; isolating them keeps the base install light.
- **Cleaner boundary** — the energy connectors already depend on **only**
  `iaiops.core` (see precondition below), so the split is a move, not a rewrite.

## Precondition — extraction-readiness (machine-checked ✅)

`tests/test_energy_isolation.py` statically asserts every `iaiops.*` import in the
energy connectors resolves to `iaiops.core` (or the connector's own package) and
that **no sibling connector** (opcua/modbus/s7/…) is imported. This is the
invariant that makes the spin-out a clean lift. Keep this test green until cutover.

## What moves vs. what stays

**Moves to `industrial-aiops-energy` (new repo):**
- `iaiops/connectors/iec104/`, `iaiops/connectors/dnp3/`, `iaiops/connectors/iec61850/`
- their tests (`tests/test_iec104*.py`, `test_dnp3*.py`, `test_iec61850*.py`,
  `tests/test_binding_contracts.py` energy rows, `test_energy_isolation.py`)
- the energy MCP tool modules + the `energy` profile entry + `iaiops-mcp-energy`
  entrypoint + the `iaiops[energy]` / `iaiops[iec104|dnp3|iec61850]` extras
- energy docs rows (README validation banner energy lines, ROADMAP energy items)

**Stays in `iaiops` (base package, the new repo depends on it):**
- `iaiops.core` — governance / brain / runtime / normalized model / sinks
- shared connectors the energy profile *reuses* — `opcua`, `modbus` (the energy
  repo depends on `iaiops` for these; it does not copy them)
- the profile/entrypoint machinery (must become plugin-discoverable — see steps)

## Dependency direction

```
industrial-aiops-energy  ──depends on──▶  iaiops (core + opcua + modbus + brain)
        (iec104 / dnp3 / iec61850)                    ▲ never the reverse
```

The core must never import an energy connector. The energy repo pins
`iaiops>=<current>,<next-major>`.

## Required enabling change (do this in the base repo *before* cutover)

The profile menu (`mcp_server/profiles.py` `NAMED_PROFILES` / `PROTOCOL_MODULES`)
currently hardcodes protocol→module and edition membership. For an out-of-tree
edition it must become **plugin-discoverable** (Python entry-points group, e.g.
`iaiops.connectors` and `iaiops.profiles`), so the energy package can register
`iec104/dnp3/iec61850` + the `energy` profile without editing the base repo. This
is the one real code change the split requires; everything else is a file move.

## Migration steps (phased, base repo stays green throughout)

1. **Base repo:** add entry-point discovery for connectors + profiles (above);
   keep the built-in registrations working. Ship it; quality gates green.
2. **New repo** `industrial-aiops/industrial-aiops-energy`: create with the same
   governance/quality tooling (ruff + bandit + pytest, `_is_governed_tool` gate,
   brand-isolation wordlist). Identity: `wei <zhouwei008@gmail.com>` only.
3. **Move** the three connectors + their tests + energy profile/extra/entrypoint
   via `git mv` (preserve history if possible); wire them through the new
   entry-points; depend on `iaiops`.
4. **Base repo:** delete the moved connectors + energy extra/profile; leave a note
   in ROADMAP (and the internal HLD) pointing at the new repo.
   `test_energy_isolation.py` moves with the connectors.
5. **Verify** both repos: `iaiops[energy]` from the new repo reproduces today's
   `IAIOPS_MCP=energy` tool set; energy tests pass against the same fixtures
   (IEC-104: c104 symbol/surface pass 2026-06-30 — a genuine loopback round-trip
   first passed 2026-07-13 in `iaiops-energy`, `tests/test_iec104_live.py`;
   contract tests for DNP3/61850).
6. **Publish** the energy package (PyPI + MCP registry) under its own name with an
   **independent PyPI token** (never reuse another line's token).

## Quality gates (both repos, unchanged)

`pytest` + `ruff` + `bandit` (0 Medium+); every MCP tool carries
`_is_governed_tool`; zero cross-brand banned words; destructive ops stay dry-run +
double-confirm + undo. Energy edition remains read-first (no control writes).

## Non-goals / open items

- Not creating the external repo here (needs go-ahead).
- 电力行业等保 / 电监会安全防护 mapping deltas → track in the energy repo's compliance
  map once split (base repo now carries the 防护指南 / 等保 2.0 / IEC 62443 crosswalk —
  see `docs/CHINA.md §5.1`).
- Live-IED / live-outstation validation (DNP3, IEC-61850) stays 待核实 until real
  gear is available — see the preview-protocol verification runbook.
