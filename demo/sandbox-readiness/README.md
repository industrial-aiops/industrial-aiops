# Sandbox diagnostic readiness — first reference slice (0.35.0)

One platform, one **synthetic conveyor** and a closed observation window. This
local card separates supplied configuration readiness from actual sample
sufficiency. It reuses `measure_availability`; a run-state signal establishes
**that a stop occurred**, never its physical cause. This is a reference
observation capability, not the complete RCA/readiness surface.

## Reproduce without devices or an external model

Install iaiops 0.35.0, then run the reference data harness from the repo.
For a package-only deployment, invoke `iaiops diagnostic-card` with the two
JSON inputs; the application must use its installed CLI, without PYTHONPATH overlays:

```sh
IAIOPS_HOME=/tmp/iaiops-readiness-demo .venv/bin/python \
  demo/sandbox-readiness/run_demo.py --out-dir /tmp/iaiops-readiness-results
```

Use a new output directory for each run. The script invokes the normal governed
CLI, checks both expected exit codes and each inventory hash, and extracts two
self-contained HTML cards. Open `sufficient.html` / `insufficient.html` locally.
No web server, external script/font or OT protocol endpoint is involved.

| Case | Configuration | Evidence | Expected result |
|---|---|---|---|
| `sufficient.json` | Explicit endpoint/ref, state vocabulary, running values and declarant | 21 good, nonhistorical source samples, one-second cadence | One 6-second stop; root cause `null` |
| `insufficient.json` | Same mapping and policy | Critical run-state samples removed | `insufficient_evidence`, diagnostic `null` |

Both fixtures use a historical window, so `--replay` is deliberate. Their
sufficiency says nothing about current device readiness. Without `--replay`,
source/window freshness is assessed against the actual current UTC time; old
fixtures must fail. No receipt timestamp can renew source evidence. Both modes
refuse future clocks, naive timestamps, invalid/unknown states, bad quality,
historical rows, endpoint/ref mismatches, duplicates, out-of-order samples or
coverage gaps. `policy.max_gap_s` / `max_age_s` are explicit operator policy,
not a universal safety threshold. Window limit: 24 h; 100000 rows / 8 MB input.

`declared_by` records a supplied assertion; the software cannot authenticate that
a human reviewed it. **Do not infer production mappings from fixture names.**
Deployment state, source provenance and physical causes are separately unverified.

## CLI and identity

```sh
iaiops diagnostic-card --input observation.json --out evidence.zip
iaiops diagnostic-card --input demo/sandbox-readiness/sufficient.json \
  --replay --identity identity.json --out replay.zip
```

Exit codes: 0 sufficient for this capability/window; 2 unconfigured or insufficient
(with a bundle explaining the gaps); 1 malformed input, audit/export failure or
policy denial. Existing output is never overwritten. CLI policy/budget/audit
remain active, including denied calls. This slice introduces no MCP tool.

An optional identity JSON allows only these keys (string or null):
`application_package_digest`, `compose_component_digest`, `runtime_image_digest`,
`deployment_id`, `platform_version`, `source_revision`. Never supply a full WFM
application-package response: it can contain registry credentials. Missing fields
remain `missing`; provided values say `operator_supplied`, **not verified**.
For a source overlay record its candidate Git revision separately from the
base image/package digest. Do not describe it as the unchanged released package.

## Export contract

The ZIP has fixed entry names: exact `input.json`, `assessment.json`,
`identity.json`, the assessment's `audit-reference.json`, inert `card.html`, and
`manifest.json` with exact SHA-256/byte sizes of the other five entries. Files
are created exclusively with mode 0600. The manifest is unsigned and does not
hash itself. It detects accidental changes when compared to a trusted copy;
it cannot prevent an attacker rewriting both contents and manifest. The audit
reference identifies a real assessment event by workflow ID/row hash; the CLI
export completion event is recorded afterwards in the local audit DB. This is
not a full hash-chain export, signed attestation or retention guarantee.

Timing in the report covers file loading and assessment only. For a Sandbox
trial, independently record when WFM reaches INSTALLED, when human mapping and
sample input are available, and when the first evidence result is exported.
Deployment/collection time must not be disguised as local assessment duration.

Scope: no PLC writes, real process, second vendor, in-place upgrade, full RCA,
formal Margo certification, organization-level signing or retention.
