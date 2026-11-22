# Released iaiops 0.36.0 — PdM evaluation and feedback in real Sandbox

Executed 2026-11-22 (Asia/Shanghai). Tag `v0.36.0` points to
`20c52bb1fdf2b882c582c31898f5148adbd9ed6d`. This is released-package verification,
separate from the earlier local candidate record. No application source overlay,
image rebuild, package repackaging or replacement `iaiops` module was used.

## Publication and identity

[Release](https://github.com/industrial-aiops/industrial-aiops/releases/tag/v0.36.0),
[release CI](https://github.com/industrial-aiops/industrial-aiops/actions/runs/45009302190),
[PyPI](https://github.com/industrial-aiops/industrial-aiops/actions/runs/45009983179),
[images/Margo](https://github.com/industrial-aiops/industrial-aiops/actions/runs/45009983150)
and [MCP Registry](https://github.com/industrial-aiops/industrial-aiops/actions/runs/45009983190)
all finished successfully. Release CI passed all six jobs, including Python
3.11/3.12 gates, integration contracts, descriptor validation, dependency audit
and immutable-host readiness. Factory image publication initially failed because
container pip could only see versions through 0.35.0 despite host preflight
passing; rerunning failed jobs succeeded with the same commit/tag/wheel. See
`incidents.json`; no failed gate was bypassed.

| Official artifact | SHA-256 |
|---|---|
| PyPI wheel | `c397b03ee238653d93987711ee985a0f60bb618a5e19497d58d7fdbf2ea361fd` |
| PyPI sdist | `ba610753bfa876698912b100c92265f93b38e400f22cc1ad07cb32b70ff92cdb` |
| Application Package OCI manifest | `6da19c2b4806235158f660521f036f13ccc086b95057da00f9b7b87bbfcfa1e5` |
| Compose component OCI manifest | `8123375ac19e67f3ec9671dbc34cb83480248e1364f916e7947932b1d23b30fc` |
| Factory multi-arch index / actual runtime image | `61255c8bc0553876dba35792c3dda7cb6208b44b766a313a692c353a17477ea5` |
| Factory amd64 manifest | `3680fd60bd2d23acd143e712cabcbbe365b5116d1144f4c610ade207f8ad0750` |
| Factory amd64 config blob | `44306d05b9d217904cdf76d1a26f85c7b464f545af1bad33deab2c40c4efffb9` |

Both PyPI downloads matched official JSON hashes. Cosign verified the image,
Application Package and Compose OCI signatures with the repository public key,
including offline transparency-log checks. The signed release tar mirror verified
as well. Release input/harness/schema/tar and locked-dependency SBOM hashes are
in `release-asset-hashes.json`; the SBOM checksum matched. It describes the locked
dependency set, not a complete runtime-container SBOM. PEP 740 attestations were
published by CI but not independently reverified here.

## Actual deployment

The signed Application Package was mirrored unchanged into lab Harbor;
`app.digest` equals `mirror.digest`. WFM package ID:
`efdfff13-65a7-43c9-beb5-ace0fbf1a62a`; deployment ID:
`2d443e09-6cf4-429e-ba86-3ead0693c84f`. The existing WFM baseline is
margo/symphony `932ef320b6491da3ec484cf4aa2d69900dbb4445`; no upstream candidate
fix was deployed. The device agent was paused during normal desired-manifest
writes, retaining its anti-rollback protection: **13 → 14** on creation.

The first catalog import failed because an older internal Symphony solution used
the same display name. Attempting deployment with that failed package caused WFM
to panic in `MergeWithAppPackage` at `transformer.go:555`. No deployment or version
advance resulted. WFM automatically restarted; its internal solutions and
instances lists were empty afterwards. Only the failed package record was deleted
through Maestro; existing package records were retained. Reimporting the identical
package and explicitly waiting for **ONBOARDED** succeeded. The EOF/panic records
are preserved, rather than counted as a passing first attempt. These WFM defects
remain unresolved by this application release.

Direct lab GHCR downloads were slow. A first Docker save/load transport did not
retain the original compressed blobs, and the agent's Compose deployment removes
the version tag before forcing a pull. The workstation therefore downloaded and
verified every official amd64 manifest/config/compressed-layer digest and imported
an OCI archive, with a temporary cache alias retained during agent restart. Normal
agent reconciliation then deployed the application. The alias was removed during
cleanup. No application image content or deployment specification was changed.

WFM reported **INSTALLED** and `iaiops-2d443e09-iaiops-1` was **healthy**, UID 10001,
with read-only rootfs. The actual runtime image matched the signed index exactly
(`runtime-identity.json`). The contextual WFM message still says "yet to be synced"
while state is INSTALLED; container health was independently checked. Installed
metadata was **0.36.0**, evaluation engines loaded from site-packages, no
`PYTHONPATH` or `/tmp/candidate` existed and no source bind mount was present.
All **14** selected installed module hashes matched the official PyPI wheel.

## Complete reference scenario

The release assets `dataset.json` and `run_demo.py`, plus the external
`pdm036-extra-harness.py`, ran inside that installed workload. Only test inputs and
harnesses were copied to its temporary directory. The harness invokes installed
CLI commands; it does not replace product modules. Its exact executed source is
archived as `pdm036-extra-harness.py.txt`. `formal-run.sh` records the
lab execution and archive checks. Use the [released reference guide](../../../../demo/pdm-feedback/README.md)
for the portable CLI workflow; use a fresh output directory on each run.

| Check | Observed result |
|---|---|
| Five synthetic windows | TP 1 / FP 1 / TN 1 / FN 1 / abstain 1 |
| Coverage / time coverage | 0.8 / 0.8 |
| Event recall / precision | 1/3 / 1/2 |
| False alarms per scored hour | 0.5 (2 scored hours, 2.5 total hours) |
| Matched threshold lead / ETA MAE | 600 s / 0 s |
| Physical lifetime interval coverage | null |
| Pending → existing case confirm → confirmed + maintenance record | Passed; one canonical maintenance mapping, no learned weights |
| Inconclusive → existing case dismiss → false_positive | Passed |
| Premature confirmation / dismissal | Refused, no output archive |
| Conflicting maintenance cause | Refused, no output archive |
| Different policy rebinding the existing case | Refused |
| MCP no token / valid-token initialize | HTTP 401 / 200 |

All four feedback states retain `updates_applied: []`. Confirmed and false-positive
archives contain matching case-confirm/dismiss audit references; the original
evaluation reference is retained. All six ZIPs report version 0.36.0 and every
inventory file hash was independently recomputed on the device and workstation.
`verified-summary.json`, scenario logs and ZIPs preserve the results.

**The reviewer is a scripted synthetic annotation, not a real engineer/plant
confirmation.** Cause, identity, condition and unit are explicitly declared fixture
inputs. These metric values are fixture expectations, not measured predictive
performance. No PLC, gateway, real maintenance system, external model, calibrated
physical RUL or other-vendor interoperability was validated. Inventories are
unsigned reproduction evidence, not independent attestation or Margo certification.

## Cleanup

Normal deletion advanced the manifest **14 → 15**, with zero desired deployments.
The agent adopted 15, removed the application and its volume, and was recreated
with its original address-only configuration. WFM lists zero deployments; agent
running, cached deployments zero, test containers/volumes zero (`cleanup.json`).
Temporary secret variables/files, the cache alias, transport archives and private
import logs were removed. The two temporary secrets were checked absent from all
exported files and ZIP contents before removal. Anti-rollback checks were neither
disabled nor reset. The successful 0.36.0 catalog package remains for reuse.
