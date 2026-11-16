# Fledge notification context probe — 2026-11-17

## Result

The core Fledge [request #1716](https://github.com/fledge-iot/fledge/issues/1716)
reports missing triggering values in delivery-plugin reasons. At notification
service develop commit `e0e84373c5bbd2fab26c9a033c84c45812c1d260`, source inspection
found `deliverNotifications` calling `addDataToReason(reason, data)` before queueing
the same reason for the main and extra deliveries. The delivery wrapper forwards
that reason to its plugin entry point.

A local C++ harness executed the **unmodified extracted `addDataToReason` function**.
Five cases passed: 87.3, a distinct 91.7, a cleared reason with 50.0, empty data,
and escaped text. Original reason/asset/timestamp fields were preserved and the
full supplied evaluation data was available under `reason.data`. For the synthetic
single-item example, the value is `reason.data.sinusoid.sinusoid`, not a new
root-level `reason.value` field.

The function's introduction is associated with notification service
[PR #105](https://github.com/fledge-iot/fledge-service-notification/pull/105), merged
2025-07-29. This is a different repository from the issue's core Fledge repository.
Do not conclude that every released or deployed bundle contains this implementation.
The issue remains open; no public comment or change was submitted by this work.

## Scope

Only the exact reason-enrichment function was compiled; its logging sink was
replaced with a no-op. Other service code was inspected, **not executed**. No
threshold evaluation, notification queue, delivery plugin, storage service, MQTT,
container or full Fledge installation was run. Docker was unavailable locally.
This is function-level source execution, not end-to-end reproduction of the issue.

The input timestamp and values are synthetic. The timestamp field in the original
reason was preserved; no independent clock or source event-time accuracy was proven.
Window evaluation can carry aggregate data: it must not be labelled the original
triggering sample unless the actual runtime and rule behavior establish that.

## Reproduce

Requirements: Git, Python 3.11+ and a C++11 compiler (`clang++`, or use `--compiler g++`).
From the iaiops repository root:

```bash
git clone https://github.com/fledge-iot/fledge-service-notification.git /tmp/iaiops-fledge-notification
git -C /tmp/iaiops-fledge-notification checkout --detach e0e84373c5bbd2fab26c9a033c84c45812c1d260
python3 scripts/community/fledge_reason_probe.py \
  --source /tmp/iaiops-fledge-notification --out /tmp/iaiops-fledge-probe-result
```

Choose unused directories on reruns. The script checks the source commit and
rejects local changes to the inspected C++ file, records file/function hashes,
compiles the actual extracted function and checks all five output payloads.
No upstream source is vendored into iaiops. Upstream source is Apache-2.0;
temporary extracted code remains an upstream-derived local test artifact.

Recorded result:
[`notification-reason-e0e8437-2026-11-17.json`](../evidence/fledge/notification-reason-e0e8437-2026-11-17.json).

## Candidate contribution

Prepare a version-aware troubleshooting example for existing #1716 instead of
implementing a second enrichment layer. It should show a sanitized `reason.data`
example, ask for the notification-service version when the field is absent, and
include the exact distinction between single-item and window evaluation.
A complete service test is the next gate before asserting a delivery-plugin fix.

### Reviewable upstream comment draft — not sent

I checked notification-service develop at e0e8437 and found that the delivery path
adds evaluation data under `reason.data` before queueing the notification. A focused
local C++ execution of that enrichment function preserved the supplied datapoint
value and existing reason fields. This was not a full service/plugin test. Could
we compare the affected notification-service version and whether the captured
reason includes a nested `data` object? I can prepare a small versioned example
covering single-item data versus window aggregates.

## Next local experiment

On a disposable Linux test environment with the pinned service dependencies:

1. Configure a single-item threshold and a capture-only delivery plugin.
2. Supply 87.3 above threshold 80, then a distinct value and a clear transition.
3. Capture the **actual plugin argument**, not merely `ThresholdRule::reason()`.
4. Repeat with a window aggregate and label the evidence appropriately.
5. Compare older/newer service versions before proposing a compatibility test.

No automatic access to an external lab, production network or public service is
part of this probe. This work does not introduce a Fledge runtime dependency into
iaiops or assert an operational integration.

## Validation of this handoff

Five C++ function cases passed; 34 existing Sparkplug/cache regression tests
passed after merging #300. Ruff check/format, whitespace and Bandit Medium+ gates
passed. No production iaiops runtime or dependency was changed for the Fledge probe.
