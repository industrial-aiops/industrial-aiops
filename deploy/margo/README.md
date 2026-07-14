# `deploy/margo/` — iaiops as a Margo edge-application (skeleton)

> **Status: roadmap `⏳` — NOT Margo-compliant yet.** This is the container + application-description
> **skeleton** for packaging iaiops as a [Margo](https://margo.org/) edge application. The exact
> app-package schema and a passing conformance-toolkit result are still `待核实`. See
> [`../../docs/MARGO-ALIGNMENT.md`](../../docs/MARGO-ALIGNMENT.md) for the full plan and honesty note.
> No material claims *Margo-compliant* until the conformance result exists.

## What's here

| File | Purpose |
|------|---------|
| `Dockerfile` | Reproducible, **non-root**, read-only-rootfs-friendly image. Installs the published `iaiops[<profile>]` wheel; headless MCP entrypoint. Build-arg `PROFILE` = edition. |
| `compose.yaml` | Example hardened run (Podman/Docker): `read_only`, `cap_drop: ALL`, no-new-privileges, single **IP-allowlisted** MCP port (socket transport — no OT inbound), single config/secret volume. |
| `margo.yaml` | Margo **ApplicationDescription**, built to the real **`margo.org/v1-alpha1`** schema (docs.margo.org, PR1 pre-draft): compose `deploymentProfiles` / `components` / `requiredResources` / `parameters` / `configuration`. Remaining `待核实` = only the hosted+signed package location/key and the secret-parameter flag pending [`margo/specification#145`](https://github.com/margo/specification/issues/145). |
| `.dockerignore` | Keeps the build context tiny (image installs from PyPI). |

## Quick start

```bash
# Build the factory-edition image (fab | factory | process | building | water)
docker build -t iaiops:factory --build-arg PROFILE=factory -f deploy/margo/Dockerfile .

# First-time setup writes into the state volume (encrypts credentials)
docker compose -f deploy/margo/compose.yaml run --rm iaiops iaiops init
docker compose -f deploy/margo/compose.yaml run --rm iaiops iaiops doctor

# Run the headless MCP server (factory profile)
docker compose -f deploy/margo/compose.yaml up
```

## Transport: stdio vs socket

The image speaks MCP over **stdio** by default (fine for a local `docker run … | client` pipe). A
Margo/edge deployment fronts it as a **socket** instead — the shape the app-package WG recommends
(one container port, no protocol glue). Select it with three env vars (already set in `compose.yaml`):

```bash
IAIOPS_MCP_TRANSPORT=streamable-http   # or: sse
IAIOPS_MCP_HOST=0.0.0.0                 # bind inside the container
IAIOPS_MCP_PORT=8000                    # the one inbound MCP tool port (not an OT port)
IAIOPS_ALLOWLIST_IPS=10.0.0.0/24        # who may call it (403 otherwise) — set to the orchestrator
```

The OT side stays strictly **outbound** to the endpoints in `config.yaml`; the socket port is only
the tool interface for the orchestrator/agent.

## Why this is a good Margo citizen (already)

- **Non-root, read-only rootfs, outbound-only to OT** — the single inbound port is the IP-allowlisted
  MCP tool interface, not an OT listener.
- **Governed by construction** — audit / budget / risk-tier / undo + MOC gating wrap every tool.
- **Air-gap friendly** — pure-Python, offline wheelhouse install, encrypted local secrets, optional
  on-box LLM brain (data never leaves the plant).

## WG questions — answered (app-package-definition-wg, 2026-07-13, ABB / P. Presson)

The three open questions posted to the WG ([Discourse t/43](https://discourse.margo.org/t/governed-mcp-based-ot-diagnostics-as-a-margo-edge-application-reference-feedback/43)) were answered:

1. **MCP transport** — *out of Margo's scope*; socket recommended for deployment simplicity. → this
   skeleton now defaults the deployment to the **streamable-http socket** transport (above).
2. **Profiles** — *either idiom is valid.* → we keep **one parameterised application** (the `profile`
   parameter), not N packages.
3. **Secrets / least-privilege** — *no secret-typed parameter in the spec yet*, tracked at
   [`margo/specification#145`](https://github.com/margo/specification/issues/145). → `masterPassword`
   is modeled as a **reference** (empty in the descriptor, injected from the device secret facility);
   iaiops resolves every credential from its on-box encrypted store **by name**, so secret values
   never travel in the descriptor or deployment spec. We'll contribute this reference-model as a use
   case on #145.

Full detail + the contribution plan: appendix B of [`../../docs/MARGO-ALIGNMENT.md`](../../docs/MARGO-ALIGNMENT.md).
The remaining `待核实` are only the hosted+signed package location/key and the conformance run.
