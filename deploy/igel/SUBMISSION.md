<!-- Ready-to-paste answers for the IGEL Ready Guided App Submission Workflow. Filled to the
     extent possible without an IGEL Ready account; the account/submission itself is email-gated
     (needs a business-domain email or a warm intro — see §4). Same 待核实 discipline as the repo. -->

# IGEL Ready — submission answer sheet (Managed Container)

Ready-to-paste answers for the Guided App Submission Workflow (App Creator Portal,
`appcreator.igel.com`). Route: **Managed Container (OCI)** — recommended for a headless
Python container workload. Identity throughout: **wei `<zhouwei008@gmail.com>`**.

## 1. Application identity

| Field | Value |
|---|---|
| App name | Industrial-AIOps (`iaiops`) |
| Tagline | Governed, vendor-neutral OT read tap + cross-protocol RCA, as MCP tools |
| Category | Industrial / IoT / Edge diagnostics |
| Vendor | Industrial-AIOps (independent) |
| Version | 0.15.0 (SemVer; `public_version` absent until IGEL assigns one) |
| License | MIT (core); optional proprietary `iaiops-enterprise` layer |
| Homepage | https://github.com/industrial-aiops/industrial-aiops |
| Container image | `ghcr.io/industrial-aiops/iaiops:0.15.0-<profile>` (public GHCR, multi-arch amd64/arm64) |
| Image signature | cosign-signed; verify key `deploy/margo/cosign.pub` |

## 2. Deployment (Managed Container)

- **Image**: `ghcr.io/industrial-aiops/iaiops:0.15.0-factory` (or `fab`/`process`/`building`/`water`).
- **Runtime posture**: non-root (uid 10001), read-only rootfs, `cap_drop: ALL`, no-new-privileges,
  one loopback-published MCP port (8000). No inbound OT listeners — the OT side is strictly
  **outbound** to the operator-configured endpoints.
- **Transport**: MCP over a socket (`IAIOPS_MCP_TRANSPORT=streamable-http`, port 8000) — runs
  headless under the container runtime; no attached stdio client needed.
- **State volume**: `/home/iaiops/.iaiops` (config + encrypted secrets + audit/undo store).
- **Secrets**: injected at deploy time from the device secret facility into `IAIOPS_MASTER_PASSWORD`
  (reference model — the value never travels in any descriptor). All OT credentials resolve on-device
  from the encrypted store by name.
- Reference manifests: [`../margo/package.compose.yaml`](../margo/package.compose.yaml) (compose) and
  [`app-recipe/`](app-recipe/) (native systemd unit, if a native App Portal entry is preferred).

## 3. Security review — anticipated questions

| Question | Answer |
|---|---|
| Inbound network exposure? | One loopback-bound MCP tool port (8000). No inbound OT ports. |
| Outbound? | Only to the OT endpoints the operator configures (OPC-UA/Modbus/… hosts). |
| Runs as root? | No — uid 10001, read-only rootfs, all caps dropped. |
| Writes to OT devices? | Read-first. The few write tools are OFF by default and gated (dry-run + one-shot approval token + undo capture + hash-chained audit). |
| Data egress / telemetry? | None. Air-gap friendly; optional on-box LLM (`docs/AIRGAP.md`). No phone-home. |
| Supply-chain integrity? | Image cosign-signed; wheels on PyPI; CI gate (pytest + ruff + bandit 0 Medium+). |
| Secrets handling? | Encrypted on-device store; injected by reference, never embedded in manifests. |

## 4. Account / submission status (待核实 — needs user action)

- IGEL Ready membership + the App Creator Portal are **email-gated**: the contact form rejects
  consumer email (gmail). Two ways in: a **business-domain email**, or a **warm intro from an IGEL
  contact** (Raymond Lucassen, IGEL presales — the emerging validation partner; his personal domain
  is `edge2go.group`). Until one is in place, this sheet is submission-ready but cannot be filed.
- Terms/fees of IGEL Ready: `待核实`.
- On a real IGEL OS 12 box, validate: Managed-Container config surface, secret-injection mechanism,
  registry reachability, and the `rw_partition` size in `app-recipe/app.json` — each a
  `待核实 → verified` row.

## 5. Grass-roots alternative (no account needed)

The `app-recipe/` here is written to be contributable as-is to
[IGEL-Community/IGEL-OS-APP-RECIPES](https://github.com/IGEL-Community/IGEL-OS-APP-RECIPES) —
zero-gate exposure while the IGEL Ready application proceeds. (Issue #518 already asked that repo for
the preferred container-app pattern.)
