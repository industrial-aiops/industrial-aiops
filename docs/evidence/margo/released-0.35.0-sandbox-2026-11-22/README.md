# Released iaiops 0.35.0 — real Sandbox package-only validation

Executed 2026-11-22 (Asia/Shanghai). Release tag `v0.35.0` points to
`dc5403f3751f79ac25a5e93eab2fda18538d99d6`. This supersedes the candidate
source-overlay trial **only for the reference scenario below**; the older report
remains a historical record. No application source was copied into this workload.

## Published and checked

[Release](https://github.com/industrial-aiops/industrial-aiops/releases/tag/v0.35.0),
[release CI](https://github.com/industrial-aiops/industrial-aiops/actions/runs/44991215694),
[PyPI publication](https://github.com/industrial-aiops/industrial-aiops/actions/runs/44991735128),
[images and Margo publication](https://github.com/industrial-aiops/industrial-aiops/actions/runs/44991735133),
and [MCP Registry publication](https://github.com/industrial-aiops/industrial-aiops/actions/runs/44991735156)
all completed successfully. The release version-parity check initially caught
four stale vendor delivery guides; those were corrected before tagging. No
failed release gate was bypassed.

| Official artifact | SHA-256 |
|---|---|
| PyPI wheel | `6d2cc3f1e3dc16870421f0d9842fc94c72d544770e09bc625d95288b5435a443` |
| PyPI sdist | `392e26643ea60c40ef4398e4b938b8e1500a98c2270d327eb25ec80737492d4f` |
| Application Package OCI manifest | `3dedfbf46be58426fd2b19754b89e0e171a9f1916121d6aca361877fe5bfffe9` |
| Compose component OCI manifest | `9ff5263e7ca349450f8da118ad2ba744e59dea97307ac2e7ec3c35f27d291db0` |
| Factory image multi-arch index | `8560f4f79c2ce6ce8d391712570a2a63f8846307e5c530b8632fc4ada0fdeb44` |
| Factory amd64 manifest | `3a12e83d1028f9e5de11bc3e3e45acb7e833a48253a4b98ab50d5814480a6ddc` |
| Factory amd64 config blob | `2eb1b0847b438ad39a923e4eec9309afe681f1826885035b3965005921228f2c` |

Both PyPI downloads matched the official PyPI JSON hashes (`pypi-verified.json`).
Cosign verified the image, Application Package and Compose component with the
repository public key, including its offline transparency-log checks; their
verification logs are attached. The signed release tar mirror also verified
(`tar-signature.log`). The locked-dependency SBOM and its checksum were downloaded
and checked; it describes the locked dependency set, not a full runtime-container
SBOM. PEP 740 publication attestations were enabled by CI but not independently
reverified in this trial.

## Actual deployment and absence of source overlay

The Application Package was copied **without repackaging** into the lab Harbor;
`app.digest` and `mirror.digest` are identical. WFM package ID:
`ed97d542-262d-42e7-9255-a3950197de08`. Normal Maestro/NBI deployment created ID
`be1357a5-a662-4569-9df6-778d920fd407`. The existing reference WFM source baseline
is margo/symphony `932ef320b6491da3ec484cf4aa2d69900dbb4445`; the atomic-write
upstream candidate was not deployed. The device retained its anti-rollback guard:
normal desired-manifest version **11 → 12**, with the agent paused during the
write and resumed afterwards.

WFM reported **INSTALLED**, container `iaiops-be1357a5-iaiops-1` was **healthy**,
non-root UID 10001, with read-only rootfs (`wfm-installed.json`, `runtime.txt`,
`container-state.json`). The WFM contextual message still says "yet to be synced"
while state is INSTALLED; actual container health was checked independently.

Direct lab registry downloads were slow. The **official amd64 image**, pulled
and signature-checked on the workstation, was transferred by `docker save/load`.
No image was rebuilt and no application module was modified. The imported config
blob matched the official config byte-for-byte (`loaded-config-proof.json`);
the **actual deployed image** matched the original signed index digest shown
above (`runtime.txt`). Intermediate transport/store manifest IDs are not used as
registry-signature proof.

Inside the deployed workload, installed package metadata was **0.35.0**, both
engines loaded from `/opt/venv/lib/python3.12/site-packages`, no `PYTHONPATH` was
set and `/tmp/candidate` did not exist (`installed-package.txt`). Five installed
module hashes exactly matched the downloaded official PyPI wheel
(`installed-module-hashes.json`, `wheel-module-hashes.json`). Only release JSON
inputs/identity and external test-harness input were supplied; no source tree or
replacement `iaiops` module was mounted or copied.

## Runtime results

| Input/check | Result |
|---|---|
| Official sufficient JSON, replay | CLI 0; one 6-second stop; physical root cause null |
| Official insufficient JSON, replay | CLI 2; insufficient evidence; diagnostic null |
| Sufficient JSON without replay | CLI 2; stale window; diagnostic null |
| MQTT on the installed package | 20 fresh sessions, each with exactly one QoS-1 publication, all read back correctly; silence expired |
| MCP without token / valid-token initialize | HTTP 401 / HTTP 200 |

The first three results are exported as exact-input evidence ZIPs and offline
HTML cards. Each manifest's five hashes was recomputed successfully; audit-row
workflow references were retained. All three report `live_readiness: false`:
these are archived synthetic conveyor windows, not proof a current plant is
ready. The MQTT check used official Mosquitto 2 on an isolated Docker network
with no published broker port; its external harness imported the **installed**
transport, without republishing to recover a lost value (`mqtt-formal-package.json`).
The broker was stopped afterwards. This is a live software-broker transport
check, not a physical Sparkplug gateway, production collector or OEE trial.

These records do not establish physical root cause, plant safety, other-vendor
interoperability, in-place upgrade/state retention or formal Margo certification.
The inventory is unsigned local reproduction evidence; supplied identity fields
inside the card remain `operator_supplied` rather than independent attestation.

## Cleanup

Normal deletion advanced the desired manifest **12 → 13** with no deployment.
The agent adopted 13 and removed the application and its named volume; WFM lists
zero deployments (`wfm-final.json`). The agent was recreated with its original
address-only override and remains running, watermark 13, zero cached deployments.
No test container/volume remains, the temporary test environment file/override
was removed, and the agent no longer carries test secret variables (`cleanup.json`).
No stored version was lowered, rollback check disabled or private test credential
exported in these records. The 0.35.0 package remains in the lab catalog for reuse.
