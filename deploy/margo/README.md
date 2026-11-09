# `deploy/margo/` — iaiops as a Margo edge application

> **Status: packaged + signed, but NOT Margo-compliant yet.** iaiops ships as a [Margo](https://margo.org/)-style
> edge application: per-profile signed OCI images on GHCR + a signed OCI application package
> (with a signed GitHub release tarball as a mirror), descriptor built to Margo `v1.0.0-rc.3`.
> The released OCI package passed the official Application Supplier CTT runner on Ubuntu 24.04;
> a WFM/device deployment remains `待核实` — see
> [`../../docs/MARGO-ALIGNMENT.md`](../../docs/MARGO-ALIGNMENT.md) for the full plan and honesty note.
> Do not claim *Margo-compliant* from the package test alone; WFM/device verification remains.

## What's here

| File | Purpose |
|------|---------|
| `Dockerfile` | Reproducible, **non-root**, read-only-rootfs-friendly image. Installs the published `iaiops[<profile>,telemetry]` wheel; headless MCP entrypoint. Build-arg `PROFILE` = edition. The telemetry extra enters the image on the next release, not in the already published 0.33.0 image. |
| `compose.yaml` | Example hardened run for **local dev** (builds from source): `read_only`, `cap_drop: ALL`, no-new-privileges, single **token-authenticated** MCP port (optional IP allowlist) (socket transport — no OT inbound), single config/secret volume. |
| `package.compose.yaml` | **Deploy-ready** compose shipped inside the signed application package (as `compose.yaml`): references the published, version-pinned GHCR image (`profile` parameter selects the per-edition variant), same hardened posture, no build section. |
| `margo.yaml` | Margo **ApplicationDescription**, validated against the `v1.0.0-rc.3` schema: `apiVersion: v1`, compose `deploymentProfiles` / `components` / `deviceConstraints` / `parameters` / `configuration`. The component uses an OCI `repository` and `revision`; the secret-reference model remains an open point in [`margo/specification#145`](https://github.com/margo/specification/issues/145). |
| `cosign.pub` | Public verify key for the signed images and the application package (private key lives only in CI secrets — rotate by regenerating the pair + updating this file). |
| `.dockerignore` | Keeps the build context tiny (image installs from PyPI). |

## Published artifacts (per release, built by `.github/workflows/publish-image.yml`)

- `ghcr.io/industrial-aiops/iaiops:<version>-<profile>` — multi-arch (amd64/arm64), cosign-signed.
  Verify: `cosign verify --key deploy/margo/cosign.pub ghcr.io/industrial-aiops/iaiops:<version>-<profile>`
- `ghcr.io/industrial-aiops/iaiops-margo:<version>` — OCI Application Package; its compose component
  is `ghcr.io/industrial-aiops/iaiops-compose:<version>`. Both are signed by digest. These are the
  registry artifacts named by the rc.3 descriptor.
- `iaiops-margo-package-<version>.tar.gz` (+ `.sig`) on the GitHub release — a signed mirror of the
  application package: `margo.yaml` + deploy-ready `compose.yaml` + `cosign.pub`.
  Verify: `cosign verify-blob --key cosign.pub --signature <pkg>.tar.gz.sig <pkg>.tar.gz`
- CI waits for the wheel to appear on PyPI before building (the tag→PyPI race silently broke the
  v0.12–v0.14 image builds), and `tests/test_margo_package.py` lints descriptor ↔ profile menu ↔
  pip extras ↔ build matrix ↔ version pins on every CI run.

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
IAIOPS_MCP_TOKEN=<openssl rand -base64 48>  # REQUIRED off loopback: 'Authorization: Bearer <token>'
IAIOPS_ALLOWLIST_IPS=10.0.0.0/24        # optional: who may call it (403 otherwise) — the orchestrator, never 127.0.0.1/32
```

A socket bound to anything but loopback **refuses to start without a token** (or
`IAIOPS_MCP_TOKEN_FILE` pointing at a mounted secret — preferred, the value then never shows in
`docker inspect`). Off loopback the SDK's loopback-only Host check is replaced: list accepted Host
headers in `IAIOPS_MCP_ALLOWED_HOSTS` (e.g. `iaiops:*,10.0.0.5:8000`), or leave it unset and rely
on the token. Margo leaves workload-to-workload
authentication to the application, so iaiops does it; the IP allowlist is a second layer, not the
authentication.

For a mounted token file, make it readable by the container's UID 10001 (for example, owner
10001 and mode `0600`); a host-owned `0600` file causes startup to fail with permission denied.
Keep the file outside the image and remove it when the deployment is torn down.

The OT side stays strictly **outbound** to the endpoints in `config.yaml`; the socket port is only
the tool interface for the orchestrator/agent.

## Optional local health metrics (next-release candidate)

The branch adds `OTEL_METRICS_EXPORTER=none|otlp` to the Compose component and Margo parameters.
`none` is the default. With `otlp`, install `iaiops[telemetry]` and set
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` to an OTLP/HTTP collector such as
`http://127.0.0.1:4318/v1/metrics` (same network namespace) or a private IP on the site network.
Public DNS/IPs, link-local addresses, URL credentials and `IAIOPS_NO_EGRESS=1` are refused.
Only process uptime and audit event/error/availability counts are emitted; no OT values or
audit row data. The released 0.33.0 package does **not** contain this implementation.

## Why this is a good Margo citizen (already)

- **Non-root, read-only rootfs, outbound-only to OT** — the single inbound port is the token-
  authenticated MCP tool interface (optional IP allowlist), not an OT listener.
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
   never travel in the descriptor or deployment spec. The reference-model use case was contributed
   on #145 in July 2026; the specification decision is still open.

Full detail + the contribution plan: appendix B of [`../../docs/MARGO-ALIGNMENT.md`](../../docs/MARGO-ALIGNMENT.md).
The remaining `待核实` include the secret-parameter contract (#145) and deployment through a real
WFM/device. The supported-host CTT result is recorded in
[`docs/MARGO-CTT-VALIDATION.md`](../../docs/MARGO-CTT-VALIDATION.md). The runner is now on
[`margo/conformance_test_toolkit` main](https://github.com/margo/conformance_test_toolkit); a schema
pass alone does not establish conformance.
