# `deploy/igel/` — iaiops on IGEL OS 12 (distribution overlay)

> **One distribution target, not the core.** iaiops stays **vendor-neutral**; the neutral artifact
> is the OCI image in [`../margo/`](../margo/). This folder is a thin **IGEL-specific overlay** that
> reuses that image — analogous overlays could exist for any other edge host. Exact IGEL SDK / App
> Creator Portal / UMS specifics below are `待核实` until validated on a real IGEL OS 12 box.
> **Status: roadmap `⏳`** (see `../../docs/MARGO-ALIGNMENT.md`).

## Two routes onto the IGEL App Portal

### Route 1 — IGEL Managed Container (OCI/Podman) — **recommended**
iaiops is a headless container workload, so the natural fit is IGEL OS 12's **Managed Containers**:
point IGEL at your OCI registry and deploy the neutral `deploy/margo/` image — **no IGEL-specific
packaging code at all**.

```bash
# 1. Build + push the neutral image to an OCI registry IGEL can reach
docker build -t <registry>/iaiops:0.10.0-factory --build-arg PROFILE=factory -f deploy/margo/Dockerfile .
docker push <registry>/iaiops:0.10.0-factory
# 2. In IGEL: connect the OCI registry + deploy the container via UMS / App Portal (待核实: exact
#    Managed-Container config surface — the feature is evolving; confirm against current IGEL docs).
```
- Hardening (`read_only`, `cap_drop: ALL`, no inbound ports) carries over from `deploy/margo/compose.yaml`.
- `待核实`: MCP transport under a Managed Container (stdio vs socket/HTTP) — the same open question as
  the Margo app-package (`docs/MARGO-ALIGNMENT.md` appendix B).

### Route 2 — native IGEL App via App Creator Portal (`igelpkg` recipe)
For a first-class App Portal entry (signed, UMS-deployed) that launches the container on the
endpoint. Skeleton in [`app-recipe/`](app-recipe/), built with the IGEL SDK:

```bash
# In the IGEL SDK container, from app-recipe/ (待核实: exact SDK invocation + template version):
igelpkg build -r bookworm -a x64 -sp -sa
```
Then upload + sign in the **App Creator Portal** (community cert = Standard, org cert = Enterprise)
and deploy via **UMS**. The recipe installs a systemd unit that runs the neutral image via Podman.

## `app-recipe/` skeleton (grounded on IGEL-Community recipes, fields `待核实`)

| Path | Purpose |
|------|---------|
| `app.json` | App metadata — `version` (SemVer), `rw_partition {size, flags}`, `prefer_btrfs`. `待核实`: full required-field set (see IGEL SDK Reference Manual). |
| `igel/install.sh` | Enables the systemd service (`enable_system_service iaiops.service`). |
| `input/all/etc/systemd/system/iaiops.service` | systemd unit that `podman run`s the neutral image. `待核实`: run mode for an MCP stdio workload. |

## Neutrality note
Per the repo's brand-isolation rule, IGEL is referenced **only inside this overlay**. The published
package, its description, and the core image stay vendor-neutral. Nothing here is a stated or implied
IGEL partnership — it's a deployment recipe for one candidate host.
