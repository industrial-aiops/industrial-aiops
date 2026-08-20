<!-- Ready-to-paste answers for the Siemens Industrial Edge Ecosystem onboarding. Filled to the
     extent possible without an Ecosystem account; qualification is human-gated (§5). Same 待核实
     discipline as the rest of the repo: an unverified row says so rather than guessing. -->

# Industrial Edge Ecosystem — submission answer sheet

Route: **App Provider**, containerized app deployed via IEM to an IED/IEVD.
Identity throughout: **wei `<zhouwei008@gmail.com>`**.

## 1. Application identity

| Field | Value |
|---|---|
| App name | Industrial-AIOps (`iaiops`) |
| Tagline | Governed, vendor-neutral OT read tap + cross-protocol root-cause analysis |
| Category | Industrial diagnostics / data connectivity |
| Vendor | Industrial-AIOps (independent) |
| Version | 0.22.0 (SemVer) |
| License | MIT (core) |
| Homepage | https://github.com/industrial-aiops/industrial-aiops |
| Container image | `ghcr.io/industrial-aiops/iaiops:0.22.0-factory` — public GHCR, multi-arch amd64/arm64 |
| Image signature | cosign-signed; verify key `deploy/margo/cosign.pub`, presence recorded in the Sigstore transparency log |
| Architecture | x86-64 and arm64 (packaged separately, per platform rule) |

## 2. Use case — what a plant gets

An engineer asks *why the line stopped* and gets an answer **with citations**, not a guess.

iaiops reads 14 field protocols (OPC-UA, Modbus TCP/RTU, S7comm, Mitsubishi MC, Omron FINS,
EtherNet/IP, EtherCAT, PROFINET-DCP, BACnet/IP, HART-IP, MTConnect, IO-Link, SECS/GEM,
MQTT/Sparkplug B), normalises them into one model, and correlates evidence **across** them:
downtime root cause, ISA-18.2 alarm-flood analysis, "where did the data stop" localisation, data
trustworthiness scoring, OEE with energy baseline deviation, predictive-maintenance degradation
bands, and a cross-protocol asset model.

Three properties that matter on an IED:

- **No GPU, no model API.** 45 analytic modules, none of them LLM-dependent. Deterministic
  algorithms over supplied series.
- **Refuses to guess.** With thin evidence it returns `insufficient_evidence` and names the data it
  still needs, rather than inventing a cause.
- **Runs fully offline.** Verified with the container's network disabled: the tool surface loads and
  an outbound connection attempt is refused.

## 3. Deployment on Industrial Edge

- **Definition**: [`docker-compose.yaml`](docker-compose.yaml) in this folder, imported by IEAP.
- **Resources**: `mem_limit: 1g`, `mem_reservation: 256m`, `cpus: 1.0`.
- **Posture**: non-root (uid 10001), `read_only` rootfs, `cap_drop: ALL`,
  `no-new-privileges:true`. **No privileged mode and no host networking are requested.**
- **Network**: joins `proxy-redirect`. One MCP port (8000), IP-allowlisted. **No inbound OT
  listener** — the OT side is strictly outbound to the endpoints the operator configures.
- **State**: named volume `iaiops-state` → `/home/iaiops/.iaiops` (config, encrypted secrets,
  hash-chained audit, undo store). Must survive app updates.
- **Secrets**: injected at deploy time into `IAIOPS_MASTER_PASSWORD` from the device secret
  facility — the value never travels inside the `.app`. All OT credentials then resolve on-device
  from the encrypted store by name.
- **Data domain**: IoT Data Domain (`待核实` — confirm the platform's classification with Siemens).

## 4. Security review — anticipated questions

| Question | Answer |
|---|---|
| Inbound exposure? | One MCP port on `proxy-redirect`, IP-allowlisted. No inbound OT ports. |
| Outbound? | Only to the OT endpoints the operator configures, plus any egress target they explicitly enable. |
| Runs as root? | No — uid 10001, read-only rootfs, all capabilities dropped. |
| Privileged mode / host network? | **Not requested.** |
| Writes to OT devices? | Read-first. 161 of 172 tools are reads. The 11 writes are off by default and gated: dry-run, one-shot approval token, before-state capture, hash-chained audit. |
| Data egress / telemetry? | **None by default** — no phone-home. Six tools *can* send data off-box by design (historian push, message-bus publish, on-box LLM narration); `IAIOPS_NO_EGRESS=1` withholds all six, enforced at registration and fail-closed. |
| Supply-chain integrity? | cosign-signed image + Sigstore transparency log; wheels on PyPI; CI gate = pytest + ruff + bandit (0 Medium+). |
| Vulnerability handling? | Version updates published to GHCR; the same image feeds every distribution target, so one fix covers all. |
| SBOM? | Producible from the image; `待核实` whether Siemens requires a formal submission. |

## 5. Programme status (`待核实` — needs user action)

- Qualification is **human-gated**: contact `industrialedgeecosystem.industry@siemens.com` and
  Siemens' Ecosystem team assesses the use case. There is no self-serve funnel.
- **Seller onboarding requires a company entity** (background check incl. export control), not an
  individual.
- Contract stack to sign: Ecosystem Agreement, Annex 1 Acceptable Use Policy, Annex 2 Antitrust Code
  of Conduct, App Developer Supplemental Terms, Supplier Code of Conduct.
- **No membership fee, no listing fee.** A transaction cut applies to revenue; the percentage is
  disclosed under the agreement and is **not public**.
- Review duration: Siemens publishes **no SLA**.

## 6. What we can do without any of the above

The marketplace is **explicitly non-exclusive**, and apps may use alternative delivery channels. A
`.app` can be handed to a customer who imports it into their own IEM directly. That is the path to
a first reference deployment, and a named customer is precisely what makes the qualification
assessment in §5 straightforward.
