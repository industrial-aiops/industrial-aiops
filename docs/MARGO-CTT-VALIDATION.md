# Margo Application Supplier CTT — v0.32.0 through v0.34.0 evidence

> This is a test record, not a Margo compliance claim. The CTT is under active
> development; a package-validator pass does not demonstrate deployment through a
> workload fleet manager or operation on an edge device.

## Subject and tool

- Subject: released `ghcr.io/industrial-aiops/iaiops-margo:0.32.0` OCI Application
  Package, not an uncommitted descriptor. The signed release tarball
  `iaiops-margo-package-0.32.0.tar.gz` has SHA-256
  `35ae8db036006fb4840d904f55339d763e15415f366c3d3d4b85764a5049f45e`.
- Tool: [`margo/conformance_test_toolkit`](https://github.com/margo/conformance_test_toolkit)
  commit `59b13482c95f98b5793b87c14aeddb677343b013` (2026-10-27), Application
  Supplier runner. The runner targets specification `v1.0.0-rc.3`.
- Local preflight host: macOS arm64, Go 1.26.4, **outside the toolkit's supported
  Ubuntu 24.04 environment**. To build while `proxy.golang.org` was unreachable,
  the temporary CTT checkout's `go.mod` used local source replacements cloned at
  the five required module versions. No CTT Go source file was changed.

## Results — 2026-11-01

| Check | Observation | Limit |
|---|---|---|
| Extracted release archive | CTT reported `PASSED`; Application Description and Compose component repository checks passed. | Registry checks were `NOT RUN` because the input was a local folder. |
| Released OCI reference, local preflight | CTT reported `PASSED`: 67 checks, 61 passed, 0 failed, 0 warnings, 1 not run, 4 not applicable, 1 info. [macOS HTML report](evidence/margo/ctt-app-supplier-v0.32.0-2026-11-01.html). | macOS is outside the toolkit's supported host environment. |
| Released OCI reference, supported host | The same Application Supplier runner reported `PASSED` with the same 67/61/0/0/1/4/1 counts on `Open-test` (Ubuntu 24.04, x86_64, Go 1.24.9). [Ubuntu HTML report](evidence/margo/ctt-app-supplier-ubuntu2404-v0.32.0-2026-11-01.html), SHA-256 `ff7b49c1840220fd80f9a2d53685a141e417887339a45dc7ace513a557c6abfb`. | The not-run row requires observing a running workload's alternative telemetry export; the info row says OTLP is not declared. No WFM/device deployment occurred. |
| Signature | `cosign verify-blob` accepted the release tarball; `cosign verify` accepted both the Application Package and Compose OCI component against the committed public key. | `--insecure-ignore-tlog=true` was used, so this verified the signatures and key claims, **not** Rekor transparency-log inclusion. The CTT checks signature presence, not the full cryptographic verification. |
| Existing package tests | `PYTHONPATH=. pytest -q tests/test_margo_package.py`: 13 passed. The descriptor also had zero errors against the CTT-bundled JSON schema. | These are local structural checks. |

The OCI CTT report marks the old PGP requirement
`MARGO-APP-APPLICATIONDESCRIPTION-004` as `N/A` after the OCI migration; the
Compose signature requirement accepts cosign as a recommended signature form.
The separate [OCI signing SUP #100](https://github.com/margo/specification-enhancements/pull/100)
is still a draft and may change future requirements.

## Supported-host reproduction — 2026-11-01

The published OCI reference was retested on the lab VM `Open-test` with Ubuntu
24.04 x86_64 and Go 1.24.9. The CTT source was exported from the exact commit
above and its Go source was unchanged. Because `proxy.golang.org` was unreachable
from the VM, five dependencies were copied from the version-pinned local clones
and referenced through temporary `go.mod` replacements. The binary was compiled
on the VM and run from `ctt-runner/app-supplier/scripts/`:

```bash
~/margo-ctt-20261101/margo-ctt-app oci://ghcr.io/industrial-aiops/iaiops-margo:0.32.0
```

The generated report is retained above. The structural CTT result is verified
on its supported host. Actual deployment through a Margo WFM/device and runtime
observability remain **待核实**; this is not a Margo compliance claim.

The reports above came from the toolkit runner before the report-provenance
improvement in [`margo/conformance_test_toolkit#16`](https://github.com/margo/conformance_test_toolkit/pull/16)
was merged into the upstream `dev` branch. That change does not alter these
earlier results.

## Post-merge supported-host validation — 2026-11-08

The merged CTT `dev` commit `f6e5ef4d86019bd8f07e704923207357c34ffa1d`
was tested on `Open-test` (Ubuntu 24.04.4, x86_64, Go 1.24.9). The checkout
was clean before testing; its Go module files were not changed. On this host,
`go test ./...` passed for `ctt-runner/app-supplier`, and `bash -n
ctt-runner/ctt-start.sh` plus `git diff --check` passed. Go dependencies were
downloaded through `goproxy.cn`, without local replacements.

The interactive `bash ctt-runner/ctt-start.sh application` path selected the
released `oci://ghcr.io/industrial-aiops/iaiops-margo:0.32.0` package and
reported `PASSED`. Its [HTML report](evidence/margo/ctt-app-supplier-ubuntu2404-pr16-2026-11-08.html)
has SHA-256 `8651d91d3dd32de6ba1fccaa84aeb72b752323f3df1a624397ad66e00c5cfac0`.
It records the original OCI input, pulled manifest digest
`sha256:366d9f9293cf2630723fd8014d922419f318b75ea429b09c56b3d3084df10013`,
and the merged CTT source revision. The result is 67 checks: 61 passed, 0
failed, 0 warnings, 1 not run, 4 not applicable, and 1 info. A direct runner
invocation with the same OCI reference also reported `PASSED`.

The remaining `NOT RUN` row concerns observing an alternative telemetry export
from a running workload. No Margo WFM/device deployment or live OT hardware was
available for this run, so deployment and runtime observability remain
**待核实**. This is structural Application Supplier CTT evidence, not a Margo
compliance claim. A mutable-tag race was not injected during the live registry
run; the pinned-reference behavior is covered by the CTT unit tests and the
merged code path.

## Published-container smoke test — 2026-11-01

On the same Ubuntu VM, Docker 29.1.3 pulled the released
`ghcr.io/industrial-aiops/iaiops:0.32.0-factory` image at digest
`sha256:fa5c65bc7c6d5a04ea2a7b7f1657f498a02a609881506913596a9246a2215c1a`.
It ran as UID 10001 with a read-only root filesystem, writable `/tmp`, no
capabilities, `no-new-privileges`, a dedicated state volume, and a mounted
token file. The streamable HTTP MCP endpoint was bound to host loopback only.

| Probe | Observation |
|---|---|
| Container health | `healthy` |
| MCP `initialize` without bearer token | HTTP 401 |
| MCP `initialize` with bearer token | HTTP 200; session established |
| MCP `tools/list` | HTTP 200; 156 factory-profile tools returned |
| MCP `tools/call` for `protocols_supported` | Result returned with `isError: false` |
| State/audit | `audit.db` existed in the mounted state volume with 3 rows after the probe |

The first start failed because the host-owned token file was mode `0600` and
unreadable by UID 10001. After setting its owner to UID 10001 while retaining
mode `0600`, the same image started and passed the probes. This is a deployment
prerequisite for any secret-file injection; the shipped Compose example also
supports direct token injection. This Docker smoke test is **not** a deployment
through a Margo WFM/device and does not verify OT hardware or live telemetry.
The test container, state volume, and generated token file were removed after
the probe; the CTT workspace and pulled image remain on the VM for follow-up.

## Published v0.33.0 OCI preflight — 2026-11-09

The official Application Supplier runner at upstream `dev` commit
`f6e5ef4d86019bd8f07e704923207357c34ffa1d` pulled the **published**
`oci://ghcr.io/industrial-aiops/iaiops-margo:0.33.0` manifest
`sha256:4a3a994072fb5843946a7a11547517f8aee962bbc0bce72c1cb937a2641a4413`.
The [HTML report](evidence/margo/ctt-app-supplier-v0.33.0-local-2026-11-09.html)
has SHA-256 `cdcaf9030fff9070de9bafc198c4a4e7d81999d28a773a3015f71c32ba3d5dc0`
and records `PASSED`: 67 checks, 61 passed, 0 failed, 0 warnings, 1 not run,
4 not applicable, 1 info. The application package signature verified against
`deploy/margo/cosign.pub` with transparency-log verification explicitly skipped.

This run was on **macOS arm64 (Go 1.26.4), outside the CTT-supported Ubuntu 24.04
host**. Five pinned Go modules were sourced from their upstream GitHub tags and
replaced only in a temporary `-modfile` because the Go module proxies were
unreachable; the CTT Go sources and the released OCI artifact were not changed.
The supported-host repeat is recorded below.
`MARGO-APP-OBSERVABILITY-004` is `N/A` because the released Compose component
does not declare OTEL variables. The `-003/-005/-006` row is still `NOT RUN`:
current CTT code marks it so unconditionally, even if OTLP is declared. The
new optional local-health exporter now on `main` is **not in the
released 0.33.0 image or OCI package**. No WFM/device deployment occurred in
this preflight.

**Component-format gap found by independent review:** the rc.3
[Compose Component Registry specification](https://docs.margo.org/specification/applications/application-registry/#compose-component-registry)
requires one `.tar.gz` layer with `artifactType`
`application/vnd.org.margo.component.compose+json`, layer `mediaType`
`application/vnd.org.margo.component.compose.tar+gzip`, and required layer
annotations. An independent `oras manifest fetch` of the published 0.33.0
`iaiops-compose` digest
`sha256:16b3f61fcd038129bba439e133818bb208604e9f7a2f57132c140564bdfeafa8`
showed `artifactType: application/vnd.docker.compose.project` and one direct
`compose.yaml` layer of `application/vnd.docker.compose.file+yaml` media type. The
official sandbox's Compose device client searches for a pulled `.tar.gz` file,
so the unmodified 0.33.0 component cannot satisfy that path. **The 61/67 CTT
result did not test this format requirement.** The correction merged to `main`
in #289 and updates the next release's publishing workflow; any 0.33.0 sandbox
conversion must be recorded as a separate experimental artifact with its own
digest and signature status, not described as deployment of the original signed
component.
The corrected archive was pushed only to a **local OCI layout** with
ORAS 1.3.0: one tar.gz layer, both required media types, and type/version layer
annotations; the archive contains only `iaiops/compose.yaml`. This checks the
new publishing shape, not a released registry artifact or device deployment.

Upstream [CTT #16](https://github.com/margo/conformance_test_toolkit/pull/16)
merged into `dev` on 2026-11-06. Its follow-on
[#17](https://github.com/margo/conformance_test_toolkit/pull/17) targets `main`
and remained open at this check; the `dev` runner above includes #16.

## Published v0.33.0 supported-host repeat — 2026-11-09

On `Open-test` (Ubuntu 24.04.4, x86_64, Go 1.24.9), the official Application
Supplier CTT was built from clean upstream `dev` commit
`f6e5ef4d86019bd8f07e704923207357c34ffa1d` without source changes. The
runner pulled the **published** `oci://ghcr.io/industrial-aiops/iaiops-margo:0.33.0`
manifest at
`sha256:4a3a994072fb5843946a7a11547517f8aee962bbc0bce72c1cb937a2641a4413`
and reported `PASSED`: 67 checks, 61 passed, 0 failed, 0 warnings, 1 not run,
4 not applicable, 1 info. The retained [Ubuntu HTML report](evidence/margo/ctt-app-supplier-ubuntu2404-v0.33.0-2026-11-09.html)
has SHA-256 `8c213810e7838f7c292f0f8198244ed4ab2c9283b9204900d09f1fd25a9802c2`.

The same published Compose OCI component still has the direct-YAML format gap
described above. This CTT result neither validates that component's rc.3 archive
format nor demonstrates Symphony onboarding, device deployment or telemetry.

## Published v0.34.0 supported-host repeat — 2026-11-09

The published `oci://ghcr.io/industrial-aiops/iaiops-margo:0.34.0` application
package resolves to `sha256:9cf7abbe6f8ff6277d7c5d0babf885c7c2be4dc8b08786790d2f99d9e72de3c3`.
On Open-test (Ubuntu 24.04.4), the unmodified official Application Supplier CTT
`dev` commit `f6e5ef4d86019bd8f07e704923207357c34ffa1d` reported **FAILED**:
79 checks, 73 passed, 1 failed, 0 warnings, 1 not run, 3 not applicable, 1 info.
The [retained HTML report](evidence/margo/ctt-app-supplier-ubuntu2404-v0.34.0-2026-11-09.html)
has SHA-256 `f32fd824ab8f7110c4dbf74df9c5a194ed096f8f9e1ba497788aacaf880adc0b`.

The sole failure is `MARGO-APP-OBSERVABILITY-004`. The CTT reads the raw Compose
value `OTEL_METRICS_EXPORTER=${OTEL_METRICS_EXPORTER:-none}` as a literal exporter
and calls it non-OTLP. Docker Compose v2.40.3 rendered the exact published
Compose file to `OTEL_METRICS_EXPORTER=none` and
`OTEL_EXPORTER_OTLP_METRICS_PROTOCOL=http/protobuf`; the application parameter
defaults to `none` and permits opt-in `otlp`. This CTT limitation is reported as
[upstream #19](https://github.com/margo/conformance_test_toolkit/issues/19).
The 0.34.0 CTT result must **not** be described as a pass. Its runtime
observability row remains `NOT RUN`, and no WFM/device deployment occurred.

The corrected, published Compose Archive component resolves to
`sha256:cdf8852066bb79dc71cf6f8ff0609556c284c1948077e074e1e29aa6aaa4bb34`.
Independent `oras manifest fetch` showed one tar.gz layer with digest
`sha256:efc495230780955557cdac75f7eb091e580ce42c51b9c7174c72751db9ab376f`,
rc.3 artifact/layer media types and required type/version annotations. The
archive contains only `iaiops/compose.yaml`. `cosign verify` accepted both OCI
artifacts against the committed public key, and `cosign verify-blob` accepted
the release tarball (SHA-256
`dd5d74f528b14f270ecf96824164b5d02e0e57484fc8373e101983777d45edd0`).
The signature checks used `--insecure-ignore-tlog=true`, so Rekor inclusion was
not verified. These are registry/package checks, not a device pull or update.

The [v0.34.0 release](https://github.com/industrial-aiops/industrial-aiops/releases/tag/v0.34.0)
is at commit `a25f3e734ee1ca093d754fa414e799c657397476`; its PyPI wheel has
SHA-256 `22f2d868960cb21402eb3da09700ec8939918e64403f18529d310e6d78c71a25`.
The [image publishing run](https://github.com/industrial-aiops/industrial-aiops/actions/runs/42621287971)
and PyPI/MCP registry runs succeeded. Independent key verification accepted the
five `ghcr.io/industrial-aiops/iaiops:0.34.0-<profile>` image signatures:

| Profile | Multi-arch manifest digest |
|---|---|
| factory | `sha256:4719d9d57245c6a2841c6581a90bfcccc032c592bc2310df77da3e8845556f05` |
| fab | `sha256:de8f9b1a46dd58708ffd334f0cf1c5db92fe0e824d2289408cfcd91a43133ca3` |
| process | `sha256:bde3330345f98be08856ec22b44a04df76937736091eaa18b214760c3870468f` |
| building | `sha256:d1261c360a8b0455232c99419ca0ec00878cb5fd19b05b0f583d1bb093d0db8a` |
| water | `sha256:82d3e7fb5267e9df0660d4ebd269edd53c272d1c709cca5d73cbcedd76e06a9b` |

The later [Open-test Compose-host trial](evidence/margo/compose-host-v0.34.0-2026-11-09.md)
manually pulled both published OCI references with ORAS and ran the extracted
Compose file. That is a direct host test, not a Symphony/device-agent pull and
not a change to the unmodified CTT result above.
