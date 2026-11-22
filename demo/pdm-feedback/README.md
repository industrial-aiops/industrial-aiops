# Reproducible PdM evaluation and feedback — P0 candidate, unreleased

This evaluates the **existing** `pdm_forecast` with an explicitly frozen high
threshold. No fitting, classifier, new protocol, device write, model dependency,
threshold tuning, actual plant diagnosis or organization-level attestation.
The packaged version remains 0.35.0; this feature is only on the local development
branch until merged/released. Use this candidate source, not an unchanged 0.35.0 wheel.

## Run the complete isolated example

From an environment with this candidate installed:

```sh
.venv/bin/python demo/pdm-feedback/run_demo.py --out-dir /tmp/pdm-example-NEW
```

The script refuses an existing output directory, redirects HOME/config/knowledge
and audit state into that new directory, and drives the normal governed CLI.
It exports `evaluation.zip`, `pending.zip` and `confirmed.zip`, and proves an
attempt to export confirmed feedback **before** `case confirm` is refused.

The confirmation is a **scripted synthetic reviewer fixture**, using a label
predeclared by the scenario author. It does not claim a real engineer or plant
confirmed a fault. No cause is derived from the numeric trend or from audit actions.

To exercise the actual operator entrance manually:

```sh
iaiops pdm-evaluation run --input demo/pdm-feedback/dataset.json --out evaluation.zip
iaiops pdm-evaluation open-case --evaluation evaluation.zip --window detected --site pdm-demo
# Inspect the observation and evidence, then explicitly give the synthetic fixture's answer:
iaiops case confirm synthetic-motor-detected-20261120T000000 \
  --cause mechanical_fault --by 'your declared reviewer name' --site pdm-demo
iaiops pdm-evaluation feedback --evaluation evaluation.zip --window detected \
  --site pdm-demo --input feedback-request.json --out feedback.zip
```

For a false alarm use the existing `case dismiss` entrance instead. A minimal
request is `{"schema":"iaiops.pdm-feedback-request/v1","outcome":"confirmed",
"by":"your declared reviewer name"}`. No request field can supply a case label.
Use a disposable site/config for manual experiments; unlike the example script,
these individual commands use the shell operator's configured local stores.

## Evaluation contract: `iaiops.pdm-dataset/v1`

`dataset.json` is the complete example. Declare a frozen policy revision, unit,
operating condition, high warning limit, horizon (seconds) and maximum source-time
gap. Every evaluation window names its asset, original source group, condition,
unit and semantic declarant. Assets/source groups in `reference_groups` may not
appear in evaluation. Reference metadata is a split guard, **not training data**.
The code cannot establish whether supplied group IDs are aliases or thresholds
were actually frozen before a person saw the test set; those remain declarations.

A labelled threshold event must be after the observation and within the horizon;
follow-up must cover the entire horizon for **both** positive and negative labels.
Each event ID is unique: one event cannot credit multiple windows. Windows on one
asset cannot overlap, preventing exposure being counted twice. The first slice
requires one policy/unit/condition, UTC-aware chronological timestamps, good finite
samples, bounded gaps and at least the existing engine's 30 samples. It rejects
implicit truncation, unknown units/conditions relative to policy, future samples
outside the window, duplicates and naive clocks. The dataset itself may be an
archived synthetic scenario; there is no claim of live freshness. JSON NaN/Infinity
are invalid contracts; invalid ordinary values/quality/missing samples abstain.
Already-crossed thresholds are outside this pre-event capability and abstain.

Labels are held apart from forecasting: changing a label changes the dataset
fingerprint/metrics, **not** the prediction or its diagnosis ID. The diagnosis ID
hashes the window without its label plus frozen policy; altering samples,
provenance or policy changes the binding. Exact raw input bytes are also retained.

| Fixture | Expected |
|---|---|
| detected | alert, threshold event 600 s later: TP |
| healthy | no alert, no event: TN |
| false-alarm | alert, no event in follow-up: FP |
| missed | no alert, later abrupt threshold event: FN |
| missing | absent observations, positive label: abstain, never TN |

Expected counts: **TP=1, FP=1, TN=1, FN=1, abstain=1**. Window/time coverage 80%;
event recall **1/3**, because the unscored positive also remains in the event
recall denominator. Precision 1/2; two scored observation-hours, so false alarms
per scored hour = 0.5. The matched lead is 600 s and matched threshold-ETA MAE is
zero for this deliberately linear fixture. This is not an accuracy claim about
plants, real datasets or physical remaining useful life.

Counts TP/FP/TN/FN cover scored windows only; `unscored_events` reconciles event
recall. Coverage includes both window and duration denominators. No-event recall,
no-alert precision and no-exposure false-alarm rate are null when undefined.
Lead/ETA error are conditional on matched alerts and must be read with event
recall. Physical lifetime interval coverage is explicitly null; R² and the
existing forecast's uncertainty band are not calibrated failure probabilities.

## Feedback contract and case reuse

The machine-readable request shape is
[`pdm-feedback-request-v1.schema.json`](../../docs/schemas/pdm-feedback-request-v1.schema.json).
Python validation additionally enforces evidence/case/time/cause relationships.
The exported contract is `iaiops.pdm-feedback/v1`:

- `pending`: case exists but has no human answer; no labelled maintenance record.
- `confirmed`: existing `case confirm` produced a named cause in its existing
  taxonomy. This is a case conclusion, not proof the prediction was a TP.
- `false_positive`: existing `case dismiss` recorded that it was not an incident.
- `inconclusive`: an explicit reviewer assertion; no automatic label or maintenance
  corpus. A known incident cause and inconclusive forecast validity can coexist.

Cases carry an optional `evidence_ref`. The normal confirm/dismiss path preserves
it; legacy cases without it serialize as before. A different endpoint, onset or
evidence reference cannot reuse the bound case, including sanitized-ID collisions.
Normal re-opening cannot erase a bound case's confirmation/provenance.

Optional maintenance fields are `work_order_id`, `device_id`, `case_id`,
`diagnosis_id`, explicit canonical `cause`, `completed_at`, optional `actions`,
`notes` and explicit `signals`. Only confirmed feedback may attach them, with exact
asset/case/diagnosis/cause agreement and completion at/after the observation end.
Free text/synonyms cannot silently override the confirmed cause. The existing
`corpus_from_maintenance_log(..., learn=False)` normalizes the record. **No learned
weights, threshold edits or other updates are applied.** Feedback does not rewrite
benchmark truth, retrain, score a maintenance improvement or dispatch a work order.

## Export/audit boundaries

Evaluation ZIP: raw input, deterministic evaluation, assessment audit references,
manifest. Feedback ZIP additionally retains the original evaluation audit,
request, contract and matching local confirmation/dismissal audit references.
A bounded lookup marks missing records or possible truncation (1000 rows) explicitly;
it is not full audit-chain verification or authenticated human identity. CLI export
completion is audited afterwards in the local DB. Policy/budget/audit remain active.

Each new archive is created exclusively, mode 0600, with a fixed member inventory,
exact hashes, package metadata and selected engine-source hashes. Maximum expanded
bundle size 8 MB; at most 100 evaluation windows and the existing engine's bounded
samples. Consumers verify bytes, module compatibility and recompute evaluation
before opening a case/exporting feedback. No archive extraction or code execution.
The hashes are unsigned integrity inventories, not protection against someone
rewriting both data and manifest. They do not claim a complete dependency/source
attestation. Run with the pinned candidate for reproduction.

P1 maintenance-before/after comparison, CMMS integration, cross-site governance,
physical PdM and public-dataset validation are outside this first slice.
