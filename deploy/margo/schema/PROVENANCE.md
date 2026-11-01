# Vendored Margo Application Description schema

Everything in this directory is an **unmodified copy** of upstream Margo material,
vendored so `scripts/margo_validate.sh` can validate `deploy/margo/margo.yaml`
offline and deterministically.

| File | Upstream path (repo `margo/specification`, tag `v1.0.0-rc.3`) |
|---|---|
| `application-description.linkml.yaml` | `src/specification/applications/application-description.linkml.yaml` |
| `examples/valid-001.yaml`, `examples/valid-002.yaml` | `src/specification/applications/resources/examples/valid/ApplicationDescription-00{1,2}.yaml` |
| `examples/invalid-001.yaml` | `src/specification/applications/resources/examples/invalid/ApplicationDescription-001.yaml` |

Vendored at tag **`v1.0.0-rc.3`** = commit **`dc0bf847b300165ea6292eeb24201990da2f46b8`**
(committed 2026-09-15, "rc 3 for PR3 release"; the `plugfest-2026-10` tag points at the
same commit), fetched 2026-10-16. At that date `pre-draft` carried a byte-identical
Application Description schema. Upstream now ships one invalid example, not two.

Previously vendored: `c198139` (2026-07-21, `apiVersion: margo.org/v1-alpha1` + `kind`).
rc.3 removed `kind`, requires `apiVersion: v1`, replaced `requiredResources` with
`deviceConstraints {capacityRequirements, eligibilityRules}`, and replaced component
`packageLocation` / `keyLocation` with `repository: oci://…` + `revision` (SemVer).

## Why vendored rather than fetched at CI time

`pre-draft` is a moving branch — it changed the day before this was vendored. A gate
that fetches it live would turn an upstream edit into a red build on an unrelated PR,
and would make the gate unrunnable offline (this repo is built for air-gapped sites;
its own tooling should not need the internet either). Pinning to a commit means the
gate answers one question only: *did **we** break the descriptor?*

Upstream drift is surfaced separately by the `drift` step of the `margo-descriptor`
CI job, which is advisory (`continue-on-error`) — it reports that the schema moved and
never fails someone else's PR. Re-vendor deliberately: re-copy the files, update
the commit hash above, and re-run the gate.

## What passing this gate does and does not mean

It means the descriptor is **structurally valid** against the published
Application Description schema (v1.0.0-rc.3) — every field name, type, and
enum, checked by machine rather than by eye.

It does **not** mean iaiops is Margo-compliant. Compliance covers deployment
behaviour, device-side runtime, and management-interface interaction, and is
investigated with the Margo **conformance test toolkit**. Its Application Supplier runner was
merged on 2026-10-16 and is available on `margo/conformance_test_toolkit` main. The released
v0.32.0 OCI package passed its runner on Ubuntu 24.04; see `../../../docs/MARGO-CTT-VALIDATION.md`.
The current runner checks package structure and registry artifacts,
while live deployment through a WFM/device remains a separate verification step. See
`../../../docs/MARGO-ALIGNMENT.md` for the honest status, which this schema gate does not change.

## The control corpus is load-bearing

The two `valid-*` and two `invalid-*` examples are validated on every run alongside
our own descriptor. A validator that has silently stopped discriminating — wrong class
name, schema failed to load, tool no-ops — passes our file just as happily as a broken
one. The controls are what make a `No issues found` on `margo.yaml` mean something:
the invalid examples MUST fail, or the gate fails.
