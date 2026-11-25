# P0 PdM evaluation and feedback — local candidate, 2026-11-22

Source **a84e2337b6cf28da501e08a28e304a239a1013cf**, branch
`feat/pdm-evaluation-feedback`, base `origin/main` **1a9ad5d**. Project version
0.35.0; new code is **unreleased and not in the unchanged published 0.35.0 wheel**.
The candidate is a local editable installation. Core/module fingerprints in every
archive match this source commit; package metadata alone is not its identity.

## Executed scenario

```sh
.venv/bin/python demo/pdm-feedback/run_demo.py --out-dir /tmp/pdm-example-NEW
```

The committed input declares synthetic assets/source groups, frozen condition/unit
and threshold policy, plus held-out threshold events. It uses the existing
Theil–Sen `pdm_forecast` engine without training. The intentionally imperfect
cases produce **TP 1 / FP 1 / TN 1 / FN 1 / abstain 1**. Coverage is 80%, event
recall 1/3 (including the unscored event), precision 1/2, false alarms per scored
observation-hour 0.5. Matched threshold lead is 600 s and matched ETA error is zero.
These are fixture expectations, not measured industrial prediction performance.
Physical lifetime interval coverage is null.

The script uses isolated HOME/IAIOPS_HOME and runs the governed commands. It opens
a diagnosis-bound case, exports pending feedback, confirms premature `confirmed`
export is refused, calls the **existing `case confirm` CLI** with the predeclared
synthetic reviewer/cause, and exports confirmed feedback plus an explicit
maintenance record. The existing maintenance-log bridge returns one canonical
cause with `learn=False`, no learned weights, and `updates_applied: []`.

**The reviewer is a scripted synthetic annotation, not a real engineer/plant
confirmation.** Identity strings are assertions. It demonstrates the human-entry
workflow and refusal behavior; it does not validate a physical cause. Existing
capture/anchoring modes are retained, not turned into an independent benchmark label.

`evaluation.zip`, `pending.zip`, and `confirmed.zip` preserve exact source input,
results, request/case snapshot, hashes and audit references. The confirmed archive
has a matching real local `case_confirm_cmd` audit record and retains the original
evaluation audit reference. No unrelated audit rows or the isolated audit DB are
exported. All file hashes and source-module hashes were independently recomputed.
Unsigned inventories are not authentication or organization-level attestation.

## Checks and review

- Final functional-source non-integration regression: **4780 passed, 2 skipped,
  250 deselected**, in 178.74 s (`nonintegration-tests.log`). Skips: pnio-dcp does
  not support macOS; the missing-pyarrow error case is inapplicable with pyarrow
  installed. No unfiltered integration-suite pass is claimed.
- That broad run exposed stale local installed metadata (0.34.1) while the source
  project was already 0.35.0. Afterwards, `uv pip install --no-deps -e .` updated
  this repository's venv metadata without changing dependencies or source code.
  The final **219-pass** focused/compatibility/version/CLI/brand/model-boundary
  check and full scenario were rerun with metadata **0.35.0** (`focused-tests.log`,
  `scenario.log`). The committed ZIPs come from this final rerun, not the older
  metadata run. The broader run exercised the same final functional source.
- Repository Ruff check and format check passed (705 files).
- Bandit Medium+ scan of `iaiops mcp_server` exited 0 (`bandit.log`); no Medium/High
  finding. Existing warning-only suppression messages are retained.
- Scenario requests passed the JSON Schema validator with date-time checking;
  semantic relationships are additionally checked by the Python contract.

Manual review addressed split/unit/condition leakage, labels entering prediction
identity, overlap/double-counted events, abstention denominators, source-clock and
bad-quality refusal, case-ID collisions/rebinding and compatibility, conflicting
maintenance causes, confirmation audit linkage, bounded archive reads and
exclusive private exports. No open blocking finding remains. Existing case and
maintenance tests pass; no model dependency/MCP tool/device write was added.

## Limits

This first slice evaluates an operator-frozen **high threshold** over independent
labelled windows. It does not fit a model, prove supplied group identities, verify
when an operator chose the threshold, import a public benchmark, calibrate a
lifetime probability, compare post-repair condition, dispatch work orders or
contact devices. No Sandbox/real OT/CMMS/physical PdM claim. See the
[reference contract and reproduction guide](../../../../demo/pdm-feedback/README.md).
