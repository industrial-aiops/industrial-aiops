# Vendored Margo Application Description schema

Everything in this directory is an **unmodified copy** of upstream Margo material,
vendored so `scripts/margo_validate.sh` can validate `deploy/margo/margo.yaml`
offline and deterministically.

| File | Upstream path (repo `margo/specification`, branch `pre-draft`) |
|---|---|
| `application-description.linkml.yaml` | `src/specification/applications/application-description.linkml.yaml` |
| `examples/valid-001.yaml`, `examples/valid-002.yaml` | `src/specification/applications/resources/examples/valid/ApplicationDescription-00{1,2}.yaml` |
| `examples/invalid-001.yaml`, `examples/invalid-002.yaml` | `src/specification/applications/resources/examples/invalid/ApplicationDescription-00{1,2}.yaml` |

Vendored at upstream commit **`c198139ab06238f1b437d5839d2319aebfa9ab8b`**
(committed 2026-07-21), fetched 2026-07-22.

## Why vendored rather than fetched at CI time

`pre-draft` is a moving branch — it changed the day before this was vendored. A gate
that fetches it live would turn an upstream edit into a red build on an unrelated PR,
and would make the gate unrunnable offline (this repo is built for air-gapped sites;
its own tooling should not need the internet either). Pinning to a commit means the
gate answers one question only: *did **we** break the descriptor?*

Upstream drift is surfaced separately by the `drift` step of the `margo-descriptor`
CI job, which is advisory (`continue-on-error`) — it reports that the schema moved and
never fails someone else's PR. Re-vendor deliberately: re-copy the four files, update
the commit hash above, and re-run the gate.

## What passing this gate does and does not mean

It means the descriptor is **structurally valid** against the published
`margo.org/v1-alpha1` Application Description schema — every field name, type, and
enum, checked by machine rather than by eye.

It does **not** mean iaiops is Margo-compliant. Compliance covers deployment
behaviour, device-side runtime, and management-interface interaction, and is
established by the Margo **compliance test suite** — which does not exist yet (no
conformance repo in the `margo` org; the PM group was still scoping a first
PR1 vertical slice as of 2026-01-15). See `../../../docs/MARGO-ALIGNMENT.md` for the
honest status, which this gate does not change.

## The control corpus is load-bearing

The two `valid-*` and two `invalid-*` examples are validated on every run alongside
our own descriptor. A validator that has silently stopped discriminating — wrong class
name, schema failed to load, tool no-ops — passes our file just as happily as a broken
one. The controls are what make a `No issues found` on `margo.yaml` mean something:
the invalid examples MUST fail, or the gate fails.
