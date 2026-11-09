# Margo sandbox Compose lifecycle validation

This is the execution plan for testing an iaiops application package through
the [official Margo sandbox](https://github.com/margo/sandbox). A sandbox result
is evidence for that reference environment only; it is not a Margo compliance
claim or a commercial WFM/device qualification. Use simulated protocols, not
live OT equipment.

## Pinned subject and environment

- Pin `margo/sandbox` to commit `64d7a7433e304f1694b2f72d9bf3af288de5e368`.
- Use two Ubuntu 24.04 VMs on the same lab network: WFM/Symphony/MIS/Harbor
  (upstream guide: 8 vCPU, 16 GB RAM, 100 GB disk) and Compose device
  (4 vCPU, 4–8 GB RAM, 50 GB disk). The Helm/k3s VM is outside this test.
- Record OS, Docker/Compose, sandbox and iaiops versions, VM identities,
  allocated resources and wall-clock start/end times before installation.
- Reserve guest administrator access for the upstream install scripts. Keep
  registry and device credentials out of the repository and evidence reports.

The selected lab pair is `test-llm` (`192.168.1.25`) for WFM and `Open-test`
(`192.168.1.21`) for the Compose device. `test-llm` was snapshotted before use,
configured to 8 vCPU and booted; it has 16 GB RAM and a 70 GB disk with 54 GB
guest free. This is below the guide's 100 GB WFM disk recommendation. `Open-test`
has 2 vCPU, 32 GB RAM and 13 GB guest free, below the guide's device CPU
recommendation. Both run Ubuntu 24.04.4 and can reach each other. The scripts-only
sandbox checkout is staged at `/home/wei/workspace/sandbox` on Open-test.
Neither `wei` account has passwordless sudo. `test-llm` timed out on a GitHub
Git probe, while the same probe succeeded on Open-test; the full pinned sandbox
checkout has been relayed to `test-llm` and verified clean.
No WFM or sandbox device-agent service has been installed.
The [direct Compose-host trial](evidence/margo/compose-host-v0.34.0-2026-11-09.md)
is a separate software check, not the lifecycle below.

## Artifact gate before onboarding

1. Keep the immutable **published 0.33.0** application and component digests as
   baseline evidence. Its Compose component is a direct-YAML OCI artifact and
   cannot be presented as a valid rc.3 Compose Archive or as an unmodified
   sandbox deployment.
2. For the signed 0.34.0 release, verify the application package and Compose
   component independently by digest and against `deploy/margo/cosign.pub`.
   Inspect the component manifest: one `.tar.gz` layer, rc.3 artifact and layer
   media types, type/version annotations, and a single top-level directory
   containing `compose.yaml`. Retain the `oras manifest fetch` JSON and signature
   output. State separately whether Rekor inclusion was checked.
   The signed source artifacts have been verified, and ORAS manually pulled
   both published references on Open-test. This does not replace a sandbox
   device-agent pull or the Harbor digest mapping in step 3.
3. Mirror all required OCI artifacts to the sandbox Harbor `library` project,
   including the image, component, and an application package named
   `iaiops-compose-app-package:latest` as required by the sandbox upload guide.
   Record a source digest → Harbor digest mapping. Do not replace a signed
   source artifact silently with a converted adapter.
4. Run the official Application Supplier CTT against the **released source OCI
   reference** on Ubuntu 24.04 and retain its HTML report. The 0.34.0 run failed
   `MARGO-APP-OBSERVABILITY-004` because the CTT evaluates a raw Compose
   interpolation expression; see [`MARGO-CTT-VALIDATION.md`](MARGO-CTT-VALIDATION.md)
   and [upstream #19](https://github.com/margo/conformance_test_toolkit/issues/19).
   Do not label 0.34.0 CTT-passed. CTT does not replace the component-format check.

## Lifecycle evidence

Execute the [sandbox setup guide](https://github.com/margo/sandbox/blob/main/docs/setup-guide.md)
and [operations guide](https://github.com/margo/sandbox/blob/main/docs/operations-guide.md)
at the pinned commit. Capture the following as separate, timestamped records:

| Stage | Evidence to retain |
|---|---|
| WFM and device ready | Symphony/MIS/Harbor and Compose-agent versions, health, device identity, and successful onboarding |
| Package upload | Harbor digest, WFM catalog entry and exact descriptor revision |
| Deploy | WFM request/status, device-agent pull and Compose project status, container image digest, iaiops health probe |
| Observe | Collector receipt of the four opt-in iaiops health metrics; prove no OT samples or audit secrets are exported. Use released 0.34.0 or later. |
| Update | Old and new digest, WFM request/status, device pull, container replacement and state-volume continuity. Upstream Compose clients currently remove named volumes during update; see [sandbox #490](https://github.com/margo/sandbox/issues/490). Keep update validation open until this is fixed and retested. |
| Delete | WFM request/status, device cleanup, retained/deleted volume policy, and final absence of running workload |

For a 0.33.0 lifecycle experiment, a converted component must have its own
digest and be labelled **unsigned sandbox adapter** throughout. It cannot
validate the original signed 0.33.0 component. Use the corrected signed 0.34.0
release for the next sandbox attempt. Independently preserve the named volume
before any update until sandbox #490 is fixed.

Update [`MARGO-CTT-VALIDATION.md`](MARGO-CTT-VALIDATION.md) and
[`VERIFICATION-RECORD.md`](VERIFICATION-RECORD.md) with every executed stage,
including failures and missing evidence. Close the roadmap's sandbox gap only
after WFM onboarding, deployment, update and deletion are all observed on the
Compose device. Leave commercial WFM and immutable-host items open.
