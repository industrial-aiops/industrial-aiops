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
| `compose.yaml` | Example hardened run (Podman/Docker): `read_only`, `cap_drop: ALL`, no-new-privileges, **no inbound ports**, single config/secret volume. |
| `margo-application.yaml` | **Skeleton** Margo application description. Every unconfirmed field is marked `待核实` — the real schema comes from `docs.margo.org` + the `app-package-definition-wg`. This is the "worked example" to bring to that WG. |
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

## Why this is a good Margo citizen (already)

- **Non-root, read-only rootfs, no inbound ports** — only outbound to the OT endpoints you configure.
- **Governed by construction** — audit / budget / risk-tier / undo + MOC gating wrap every tool.
- **Air-gap friendly** — pure-Python, offline wheelhouse install, encrypted local secrets, optional
  on-box LLM brain (data never leaves the plant).

## Open questions for `app-package-definition-wg` (the `待核实`s)

1. **MCP transport** — the app exposes an MCP tool surface (stdio today), not an HTTP UI. Does the
   app-package descriptor care about the interface, or only container + config + lifecycle?
2. **Profiles** — one parameterised application, or N app packages (one per edition profile)?
3. **Least-privilege declaration** — is there a place to declare "read-first, outbound-only to named
   endpoints"?

These map 1:1 to appendix B of `docs/MARGO-ALIGNMENT.md` — post it, then reconcile this skeleton
with the answers and run the conformance toolkit.
