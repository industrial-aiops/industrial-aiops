# `deploy/igel/` — iaiops on IGEL OS 12 (distribution overlay)

> **One distribution target, not the core.** iaiops stays **vendor-neutral**; the neutral artifact
> is the **published, cosign-signed** OCI image in [`../margo/`](../margo/)
> (`ghcr.io/industrial-aiops/iaiops:<version>-<profile>`). This folder is a thin **IGEL-specific
> overlay** that reuses that image — analogous overlays could exist for any other edge host. The
> **Managed-Container route is now fully unlocked**: the image ships per-profile, signed, and fronts
> MCP as a socket (the transport question is resolved). Exact IGEL SDK / App Creator Portal / UMS
> specifics below stay `待核实` until validated on a real IGEL OS 12 box. **Status: roadmap `⏳`
> (materials submission-ready; the submission itself needs an IGEL Ready account — email-gated).**

## Getting listed — IGEL Ready + the submission workflow

Two visibility levels, pick per goal:

| | **Private** (App Creator Portal) | **Public / certified** (IGEL Ready → App Portal) |
|---|---|---|
| Who | anyone | must be an **IGEL Ready Technology Partner** first |
| Result | signed for **your own devices**; NOT on the public App Portal | IGEL **validates + certifies** → listed on the public **App Portal** (app.igel.com) |

> **Submission answers are pre-filled** in [`SUBMISSION.md`](SUBMISSION.md) — copy/paste into the
> Guided App Submission Workflow once an IGEL Ready account exists (the account is email-gated; see
> §4 there).

**To get certified (public):**
1. Join **IGEL Ready** at `igel.com/partners/technology-partners/` (ecosystem program; a warm intro
   from an IGEL contact fast-tracks it). Terms/fees `待核实`.
2. Submit via the **Guided App Submission Workflow** in the App Creator Portal (`appcreator.igel.com`).
3. IGEL tracks it in-portal: **acceptance → security review → publishing**.

**Submission requirements (App Creator Portal):**
- `app.json` — valid SemVer `version`; **`public_version` empty or absent** (kept absent here).
- `igel/thirdparty.json` — names of the binaries the app uses.
- **Dependency sources restricted to official debian/ubuntu repos** — this is why a pip/Python app is
  awkward as a *native* recipe, and why the **Managed Container route below is recommended**.

## Two routes onto IGEL

### Route 1 — IGEL Managed Container (OCI/Podman) — **recommended**
iaiops is a headless container workload, so the natural fit is IGEL OS 12's **Managed Containers**:
point IGEL at your OCI registry and deploy the neutral `deploy/margo/` image — **no native packaging,
and it sidesteps the debian/ubuntu-only dependency constraint** (deps live inside the OCI image).

```bash
# 1. Pull the PUBLISHED, cosign-signed neutral image (no local build needed) + verify it
podman pull ghcr.io/industrial-aiops/iaiops:0.15.0-factory
cosign verify --key deploy/margo/cosign.pub ghcr.io/industrial-aiops/iaiops:0.15.0-factory
# 2. In IGEL: connect the OCI registry + deploy the container via UMS / App Portal (待核实: exact
#    Managed-Container config surface — the feature is evolving; confirm against current IGEL docs).
```
- Hardening (`read_only`, `cap_drop: ALL`, no inbound ports) carries over from `deploy/margo/compose.yaml`.
- `待核实`: MCP transport under a Managed Container (stdio vs socket/HTTP) — the same open question as
  the Margo app-package (`docs/MARGO-ALIGNMENT.md` appendix B).

### Route 2 — native IGEL App via App Creator Portal (`igelpkg` recipe)
For a native signed App Portal entry that launches the container on the endpoint. Skeleton in
[`app-recipe/`](app-recipe/), built with the IGEL SDK:

```bash
# In the IGEL SDK container, from app-recipe/ (待核实: exact SDK invocation + template version):
igelpkg build -r bookworm -a x64 -sp -sa
```
Then submit via the Guided App Submission Workflow (above). The recipe installs a systemd unit that
runs the neutral image via the container runtime.

## `app-recipe/` skeleton (grounded on IGEL-Community recipes, fields `待核实`)

| Path | Purpose |
|------|---------|
| `app.json` | App metadata — `version` (SemVer 0.15.0), `public_version` absent (submission rule), `rw_partition`, `prefer_btrfs`. |
| `igel/thirdparty.json` | Binaries the app uses (container runtime). Submission requirement. |
| `igel/install.sh` | Enables the systemd service (`enable_system_service iaiops.service`). |
| `input/all/etc/systemd/system/iaiops.service` | systemd unit that runs the neutral image via the container runtime. `待核实`: run mode for an MCP stdio workload. |

## Community route (grass-roots credibility)
A recipe can also be contributed to [IGEL-Community/IGEL-OS-APP-RECIPES](https://github.com/IGEL-Community/IGEL-OS-APP-RECIPES)
— zero-gate exposure while the IGEL Ready application proceeds. `app-recipe/` is written to be
contributable there as-is.

## Neutrality note
Per the repo's brand-isolation rule, IGEL is referenced **only inside this overlay**. The published
package, its description, and the core image stay vendor-neutral — this is a deployment recipe for one
candidate host, not a stated partnership.
