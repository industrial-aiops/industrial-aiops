# Backlog

> **Status — 2026-07-13 (v0.13.0).** The remaining *genuinely-open software gaps* on this
> backlog are now shipped:
> - **D2 — BAS supervisory-controller layer** (Johnson Controls Metasys OpenBlue REST + Tridium
>   Niagara oBIX/REST, above the BACnet field connector, building edition) — **shipped 0.13.0**,
>   mock-verified in both vendor dialects; live controllers + native oBIX-XML encoding stay `待核实`.
> - **D3 — Ignition Gateway MES/SCADA read layer** (Inductive Automation Ignition HTTP/Gateway
>   web API, factory edition) — **shipped 0.13.0**, mock-verified in both `webdev` / `gateway`
>   flavors; live gateway + exact API version/paths stay `待核实`.
> - **IEC-104 verify** — scaffolded in [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)
>   **0.1.4**; stays `待核实` because `c104` will not build off-Linux.
>
> What remains is only the **C-class hardware/ops items** — the honest `待核实` list that only
> real equipment or a field deployment can close (physical RS-485 / EtherCAT bus / HART gateway /
> live HVAC / live Metasys-Niagara controllers / live Ignition gateway / substation RTUs-IEDs /
> domestic PLCs / on-box packaging & edge-host ops). See the *Beta testing & co-creation* call
> in the README and the validation matrices in `docs/`.
