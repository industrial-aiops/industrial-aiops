# WFM package identity/readiness fix — real Sandbox verification

Executed 2026-11-22 (Asia/Shanghai). Upstream [PR #93](https://github.com/margo/symphony/pull/93),
commit `316457f165e2628f7db0409e8dfa0a81f96c3d4b`, based directly on main
`932ef320b6491da3ec484cf4aa2d69900dbb4445`. The manifest-write PR #92 is independent
and was not included. This trial used a **candidate WFM**, with unchanged signed
Industrial-AIOps release packages. The WFM fix is not an upstream release or merge.

## Failure, fix and regression

Margo's transformer used the human-readable app name as Symphony's globally
unique solution display name. A second version with that name could fail
onboarding; deploying its incomplete record dereferenced a nil description and
terminated WFM. Regression tests reproduced both problems on the original source
(`before-identity.log`, `before-readiness.log`). A separate logging statement also
dereferenced missing transformation data before its existing checks ran.

The patch gives internal Symphony solutions their existing versioned application
identity as display name; catalog/descriptor names are preserved. It requires
ONBOARDED status plus a complete application identity before profile merging or
any deployment writes. Missing/failed/processing packages return HTTP 409;
unsupported profiles return HTTP 400, with NBI error-state preservation. Required
transformation fields are checked before logging. Generic Symphony uniqueness
validation remains enabled.

Tests cover an existing legacy solution, different versions and different apps
sharing a display name, reimport, ten incomplete-package cases, NBI conflict
responses, profile refusal and successful onboarded deployment. Linux Go 1.25.10
package tests, **25 race-test repetitions** and vet passed for Margo managers/vendor
and the solutions manager; the validation package also compiled/vetted (no test
files). Formatting passed. These unit checks are separate from the real trial below.

## CI status

The added [fork regression CI](https://github.com/zw008/symphony/actions/runs/45024197951)
passed on the exact candidate commit. It runs the relevant race tests and vet,
using the exact Sandbox dependency commit already referenced by api/go.mod.
Committed module files were not changed.

The [upstream PR workflow](https://github.com/margo/symphony/actions/runs/45024223954)
is **action_required**, awaiting a repository administrator's fork-workflow
approval. Attempting to start it returned HTTP 403, "Must have admin rights to
Repository". Six pre-existing fully commented workflow files also produce empty
configuration failures in the fork; they are unchanged by this PR. Consequently
this is a passing focused CI, **not a claim that all upstream CI is green**.
See `ci-status.json`.

## Candidate runtime and artifact identity

The candidate binary was built from an isolated source copy, not the dirty live
lab checkout. The three production-file hashes match the signed PR commit
(`wfmfix-source-hashes.json`). Binary SHA-256:
`e940e8250acba20a7d789902f91c9e95b5a63257ffbb44d955d5e05d14e99007`.
It was copied into a local image derived from the original WFM image, retaining
its original environment, command, host network and mounted runtime configuration.
The original container was preserved stopped. `wfm-candidate.json` records both
container/image identities; the running binary hash was checked explicitly.

The original WFM's public CA bundle had been installed in its container's writable
layer rather than its base image. The first candidate import therefore failed
Harbor certificate validation. The exact original public trust bundle was copied
and its matching hash verified before retrying; TLS verification remained enabled.
Only the failed test records were removed before retry. This environment setup
failure is separate from the fixed application-name issue.

The normal upstream Rust build required resolving its stale lockfile; the build-only
resolved lock is archived as `Cargo.resolved.lock.txt`, with its hash, isolated
Rust 1.85.1 toolchain and Go 1.25.10 settings in `build-environment.json`. A build-only
modfile points to the exact Sandbox dependency checkout. No committed module/lock
file or primary lab source/configuration was edited. This was a candidate WFM
build, not an official WFM artifact provenance claim.

Fresh Cosign verification passed for both application packages and the 0.36.0
Factory image, including the key and offline transparency-log checks.

| Official artifact | SHA-256 |
|---|---|
| 0.35.0 Application Package | `3dedfbf46be58426fd2b19754b89e0e171a9f1916121d6aca361877fe5bfffe9` |
| 0.36.0 Application Package | `6da19c2b4806235158f660521f036f13ccc086b95057da00f9b7b87bbfcfa1e5` |
| 0.36.0 Factory index / actual runtime image | `61255c8bc0553876dba35792c3dda7cb6208b44b766a313a692c353a17477ea5` |
| 0.36.0 official PyPI wheel | `c397b03ee238653d93987711ee985a0f60bb618a5e19497d58d7fdbf2ea361fd` |

Existing Harbor mirrors resolved to the signed package digests; stored parsed
package descriptions also matched the application ID/name/version. These are
registry-resolution checks, not an independently captured WFM download-digest
attestation. The generic `/solutions` endpoint has separate vendor state and was
not used as proof of the Margo manager's internal storage. The application image
was transported as verified original compressed OCI blobs, with a temporary cache
alias through the agent's normal forced pull. No application image was rebuilt,
package repackaged, source overlaid or exporter changed.

## Actual results

- A nonexistent-package negative fixture returned **409** while PENDING and again
  after FAILED; the next deployment-list request returned 200. WFM remained running
  with **zero restarts**, zero deployments and manifest version **15** throughout
  those negative checks (`negative-runtime.json`).
- Both signed releases reached **ONBOARDED simultaneously**, with the same original
  `Industrial-AIOps` name and application ID, distinct 0.35.0/0.36.0 versions and
  no deletion of the first version (`same-name-coexistence.json`).
- Normal deployment of 0.36.0 advanced the manifest **15 → 16**. Deployment
  `3a7b2c5d-9262-4ef3-962b-91342cb74c97` reported **INSTALLED** and the container was
  healthy, non-root and read-only. The actual runtime image matched the signed
  index; installed metadata was 0.36.0 and **14 module hashes** matched the official
  PyPI wheel. There was no PYTHONPATH/source bind mount (`runtime-identity.json`).
- The released synthetic PdM scenario passed evaluation, all four feedback states,
  existing confirm/dismiss audit references, maintenance feedback with no learning,
  and four refusal paths. All six evidence ZIP inventories reverified on the
  device and workstation; MCP authentication returned 401/200.

The scripted reviewer and synthetic measurements are not physical PdM accuracy,
real engineer confirmation, production OT validation or Margo certification. This
is still the same reference Sandbox, not a second vendor/platform. Collector
metric reception was **not run**; its separate pending acceptance item is in the
[roadmap](../../../ROADMAP.md).

## Cleanup and restored state

Normal deletion advanced the manifest **16 → 17**. The agent adopted 17 and
removed the application/volume. All three test package records (two valid and the
negative fixture) were deleted through normal NBI/Maestro operations; pre-existing
package records remained. Candidate WFM restart count was still zero at cleanup.
The candidate container/image tags were removed and the **exact original WFM
container and image** restored (`wfm-restored.json`). Restored WFM lists zero
deployments. The original WFM implementation is restored; the fix remains in PR #93.

The device agent was recreated with its original address-only configuration:
running, watermark 17, zero cached deployments, zero test containers/volumes, no
test secret variables/files, cache alias or transport archive (`cleanup.json`).
Exported files/ZIP contents were checked free of both temporary test secrets.
The agent was paused during desired-manifest writes because the independent
non-atomic-write defect remains in this baseline. No stored version was lowered,
anti-rollback guard disabled or device database reset. Build-only source/cache
files are separate from deployed runtime state. Terminal log whitespace is normalized.
