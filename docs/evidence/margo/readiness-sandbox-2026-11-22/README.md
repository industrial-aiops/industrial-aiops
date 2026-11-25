# Single-Sandbox diagnostic readiness candidate — 2026-11-22

Executed against candidate source **c04b732df6abc6195edd6556a18280ad8e14572e**
(branch `feat/sandbox-diagnostic-readiness`), derived from main `f76ebb9`.
Source archive SHA-256: `e4ce721f438be568b35122411a8f02d41e378b207d4873175924eddb3909c3c8`.
This is an **unreleased source overlay on the released 0.34.0 factory image**,
not verification of an unchanged 0.34.1 release or a new packaged Margo artifact.
Candidate source declares package version 0.34.1; provenance records the source
revision separately. No published OCI artifact, version or default branch changed.

## Actual platform path

The existing `test-llm` WFM (margo/symphony
`932ef320b6491da3ec484cf4aa2d69900dbb4445`) accepted deployment
`fc680976-b8e3-4908-84db-da7523b1764d` through normal Maestro/NBI operations.
The Compose device agent on `Open-test` adopted manifest **10** (previous
persisted floor **9**), fetched the released 0.34.0 Compose component and created
`iaiops-fc680976-iaiops-1`. WFM state was **INSTALLED**, and Docker health was
**healthy**. See `wfm-installed.json` and `container-state.json`. The WFM's
contextual message still says "yet to be synced" even with state INSTALLED;
we independently checked the actual healthy container, not that stale message.

Base Application Package (prior verified identity, supplied to this inventory):
`sha256:9cf7abbe6f8ff6277d7c5d0babf885c7c2be4dc8b08786790d2f99d9e72de3c3`.
Compose component (prior verified identity):
`sha256:cdf8852066bb79dc71cf6f8ff0609556c284c1948077e074e1e29aa6aaa4bb34`.
This trial did not reverify their signatures. `runtime.txt` records the actual
container image identity/user/read-only-rootfs. Identity values in the exported
card remain **operator_supplied**, not cryptographically attested.

The candidate was streamed into the container's `/tmp` tmpfs and used only by
explicit CLI processes via `PYTHONPATH=/tmp/candidate`; the baseline MCP server
continued running its installed code. Docker `cp` cannot handle this read-only
rootfs/tmpfs path in this environment, so input/output used `docker exec tar`
streams. Read-only rootfs, non-root UID 10001, dropped capabilities, token
authentication and rollback guards were retained. Random test-only secrets were
provisioned through the device-agent environment, never the application package
or exported evidence. No real OT endpoint or external model was contacted.

## Observed results

| Input | CLI exit | Result | Live readiness | Diagnostic |
|---|---:|---|---|---|
| Sufficient synthetic samples, replay | 0 | ready | false | one 6-second stop; physical cause null |
| Same declared map, critical samples removed, replay | 2 | insufficient_evidence | false | null |
| Original samples, current-time mode | 2 | insufficient_evidence (stale) | false | null |

Each ZIP contains exact source input, assessment, identity inventory, real
assessment audit-row references, an offline HTML card and SHA-256 file inventory.
All five file hashes in each archive were recomputed successfully. The raw input
is synthetic; there are no plant values or test secrets in the bundles.
`summary.json` records HTTP **401** without authentication and **200** for
valid-token MCP initialize against the actual deployed baseline server. This
checks that boundary; it is not a new MCP diagnostic-card endpoint.

WFM reports installed at **01:43:45.570931738 UTC**. The first successful
assessment was generated at **01:46:55.836588 UTC**, approximately **190.27 s**
later, including manual candidate staging and the read-only-rootfs copy retry.
The staged synthetic cases became available at **01:46:54.635080 UTC**; the
assessment followed **1.20 s** later. Its internal load/analysis timer was
**0.439 ms**. These are distinct intervals: no collection/plant setup is hidden
inside a claimed submillisecond deployment-to-diagnosis result. The result time
is assessment generation; ZIP creation/transport completes afterwards.

## Checks and review

- Latest candidate tests including malformed/NaN/huge values, stale/future/naive
  timestamps, history, bad quality, wrong endpoint/ref, missing mapping/data,
  duplicate/out-of-order/gapped samples, export hashes/no overwrite/HTML escaping,
  audit failure, policy denial, CLI governance and brand isolation: **51 passed**
  (`focused-tests.log`).
- Repository `ruff check .` and `ruff format --check .`: passed (697 files).
- Bandit Medium+ scan of `iaiops mcp_server`: exit 0 (`bandit.log`); only existing
  warning messages, no Medium/High findings.
- Manual code review covered semantic declarations, sample/time boundaries,
  audit authorization, escaped inert HTML, exclusive/private export files,
  unsigned provenance limits and model-free dependencies. No open blocking finding.
- Browser visual preview was blocked because the browser policy disallows local
  `file:` URLs. No screenshot-based visual approval is claimed; HTML generation,
  escaping, content-security-policy and exact exported bytes were checked.

Broader regression: `pytest -q -rs -m 'not integration'` completed with
**4743 passed, 2 skipped, 250 deselected**, in 883.59 s (`nonintegration-tests.log`).
Skips: pnio-dcp does not support macOS; pyarrow is installed, so the missing-extra
error case is inapplicable. This run was launched before the last leaf-level
numeric/expiry/export guards and four additional regressions were finalized;
final candidate coverage was then rerun in the **51-pass** focused check above
(including those guards, CLI policy/audit and brand/governance). The initial
25 new readiness cases plus the preexisting 4718 account for the broad total.
No unfiltered full-suite pass is claimed. Docker/hardware/external-vendor
integration is separate; the actual Sandbox trial uses the reference software stack.

## Cleanup verified

Normal WFM deletion advanced **10 → 11** with an empty desired deployment list.
The device adopted 11, removed the application and its named volume, and reported
removal. WFM lists zero deployments (`wfm-final.json`). After recreating the
agent with its original address-only override, it is running, persists watermark
11, and caches zero deployments. The test secret environment/file and temporary
override were removed; no test container or volume remains (`cleanup.json`).
No stored version was lowered, rollback check bypassed or live WFM binary patched.
The existing upstream atomic-write candidate was not deployed as part of this task.
