# Official Margo sandbox WFM → Compose device trial — iaiops 0.34.0

Executed 2026-11-09 15:50–16:17 UTC (2026-11-09/10 Asia/Shanghai). This is a
software-only lab test of the **released**, signed 0.34.0 artifacts in Margo's
reference sandbox. It is not a commercial WFM, immutable-host or OT-device test,
and does not establish Margo compliance.

## Fixed inputs and lab topology

| Item | Tested input |
|---|---|
| WFM | `test-llm`, Ubuntu 24.04.4, 8 vCPU / 16 GiB; Symphony/MIS/Harbor and K3s. |
| Compose device | `Open-test`, Ubuntu 24.04.4, 2 vCPU / 32 GiB; Docker 29.1.3, Compose 2.40.3, ORAS 1.3.0. |
| Reference code | `margo/sandbox` `64d7a7433e304f1694b2f72d9bf3af288de5e368`; `eclipse-symphony/symphony` `932ef320b6491da3ec484cf4aa2d69900dbb4445`. |
| Published Application Package | `ghcr.io/industrial-aiops/iaiops-margo:0.34.0`, manifest `sha256:9cf7abbe6f8ff6277d7c5d0babf885c7c2be4dc8b08786790d2f99d9e72de3c3`. Copied unchanged to lab Harbor `library/iaiops-compose-app-package:latest`; destination manifest digest matched. |
| Published Compose component | `ghcr.io/industrial-aiops/iaiops-compose:0.34.0`, manifest `sha256:cdf8852066bb79dc71cf6f8ff0609556c284c1948077e074e1e29aa6aaa4bb34`; the device agent fetched this OCI reference and revision. A Harbor mirror with the same manifest digest was also prepared, but the deployment pointed at GHCR. |
| Factory image | `ghcr.io/industrial-aiops/iaiops:0.34.0-factory`, local image ID `sha256:4719d9d57245c6a2841c6581a90bfcccc032c592bc2310df77da3e8845556f05`; transferred from the WFM VM to the device VM because its GHCR pull stalled. The deployment still used the released image tag. |
| Device identity | `northstarida.xtapro.docker.edge.35z9a`, client SVID `spiffe://margo.org/margo/wfm/wfm/client/docker-client`. WFM listed the device as `ONBOARDED`. |

The published OCI signatures and release hashes were verified separately in
[`MARGO-CTT-VALIDATION.md`](../../MARGO-CTT-VALIDATION.md). This trial did not
reverify signatures on the device or prove Rekor inclusion.

## Observed sequence

1. Installed the sandbox MIS and Harbor on `test-llm`, created WFM/device SVIDs,
   started Symphony, then started the official Compose device-agent container on
   `Open-test`. The agent reported capabilities and WFM listed one `ONBOARDED`
   device. No OT equipment was connected.
2. Mirrored the released Application Package to lab Harbor without changing its
   manifest digest. `wfm-cli.sh upload-app-non-interactive` imported it into WFM
   as package `df0b5b92-81e3-4bc2-bd90-136dd3a58f20`.
3. The sandbox's automatic deployment generator inserted a `servicePort`
   override absent from `margo.yaml`. WFM returned HTTP 500, yet the CLI printed
   “Instance deployment request sent successfully”; WFM listed zero deployments.
   A corrected lab deployment YAML omitted that invented parameter and named the
   published Compose repository/revision. WFM accepted deployment
   `1a067cb4-fefa-4e3c-8e74-30117e0f8852`.
4. The device fetched the Compose archive. Its first reconcile failed because the
   published Compose file requires `IAIOPS_MASTER_PASSWORD` from the device
   secret facility. We supplied random **test-only** master password and MCP token
   through the lab device-agent environment, never through the Application Package
   or WFM deployment description. After agent restart, it reported “deployment
   successful”; WFM state was `INSTALLED`, and container
   `iaiops-1a067cb4-iaiops-1` was `healthy`. An unauthenticated `/mcp` request
   returned 401; authenticated MCP `initialize` returned 200.
5. Wrote a marker to the application's named state volume, then submitted the
   same deployment name with OTLP parameter overrides. WFM created a **new** ID,
   `6fa3a49f-a1ce-494f-a28f-57f214bfcfce`, instead of updating the first.
   Deleting the first deployment removed its container **and state volume**;
   the marker was absent. This was delete/recreate, **not** an in-place update or
   a state-preserving update test. The marker's SHA-256 was
   `43b521698bcf4d408276f07292aec3d4f6d0e3dba06f653c56c217963adf8bff`.
6. The second deployment reached WFM `INSTALLED` and container `healthy` with
   `OTEL_METRICS_EXPORTER=otlp` and a private-bridge OTLP/HTTP endpoint. Official
   OpenTelemetry Collector 0.164.0 (binary SHA-256
   `5db7cf88c2e73a7fdce02b5fa967fcd5dc73bab00b871d947481918dc5093861`)
   received one metrics export containing `iaiops.process.uptime`,
   `iaiops.audit.events`, `iaiops.audit.errors`, and `iaiops.audit.available`.
   The collector's detailed log contained neither secret variable name. This was
   a standalone official Collector; the sandbox's optional Jaeger/Prometheus/
   Grafana/Loki stack was not installed.
7. Deleted the second deployment. WFM listed zero deployments; the device had
   no iaiops container or named state volume. The device remained `ONBOARDED`.
   The test-only environment file was removed, the device-agent Compose file
   restored and its container recreated without the test secrets, and the
   Collector stopped. Lab Symphony/MIS/Harbor/device-agent remain available.

## Installation adaptations and limits

- Local sandbox installer scripts were backed up and adapted to reuse existing
  Docker/Compose, a pinned local source checkout and a locally loaded Symphony
  image. Direct GitHub/Docker Hub pulls were unreliable in this lab. K3s and
  Harbor installer archives were checksum-verified before installation. These
  adaptations were **lab-only**; the published iaiops OCI artifacts were not edited.
- The sandbox CLI's false success message makes its return code unsuitable as
  proof. WFM status, device-agent logs, container health, MCP response and
  Collector receipt were checked independently.
- The reference WFM/CLI path exercised here did not offer an in-place update:
  reapplying the same name created another ID. The separate sandbox Compose
  `down --volumes` state-loss behavior is tracked in
  [margo/sandbox#490](https://github.com/margo/sandbox/issues/490). A safe update
  with preserved on-box audit/secret state remains **待核实**.
- No real OT protocol endpoint, commercial orchestration software, immutable
  host, multi-site rollout or live hardware was tested. The 0.34.0 Application
  Supplier CTT still reports one failure from its Compose expression check,
  tracked in [CTT #19](https://github.com/margo/conformance_test_toolkit/issues/19).
  Neither this sandbox run nor prior CTT results warrant “Margo-compliant”.
