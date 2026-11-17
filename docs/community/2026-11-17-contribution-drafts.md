# Community contribution drafts — 2026-11-17

No model API or secret key was used. GitHub API queries, Python standard library,
local compiler and document checks were sufficient. No community PR, issue or
message was sent. The artifacts below are ready for review, not accepted upstream.

## Fledge: documentation patch prepared

Target: `fledge-iot/fledge`, develop
`a20fc6dce1bfa47657e50760458383f815944ba2`.

Read `CONTRIBUTING.md` and `docs/plugin_developers_guide/08_notify_plugins.rst`.
The guide's example contains only reason/asset/timestamp, whereas the notification
service e0e8437 enrichment probe retained supplied values under `reason.data`.
This is a documentation gap worth clarifying, not proof that every deployed
version supplies the field or that issue #1716 is resolved.

Prepared artifacts:

- [Applicable upstream patch](contributions/fledge-notification-context.patch).
- [Proposed PR text](contributions/fledge-notification-pr-body.md).

The patch adds an optional-data example and compatibility/window-evaluation notes.
It does not modify the API, delivery code or other documentation examples. The
example is illustrative, based on supplied single-item evaluation data; it is not
labelled a captured delivery-plugin argument.

Validation executed: `git apply --check`, actual application against the pinned
source, exact output comparison, and docutils rendering of the added fragment
with `--halt=warning`. A full Fledge Sphinx build and live plugin capture were not
run. Upstream code remains outside this repository; the patch contains minimal
context from the Apache-2.0 project and newly authored documentation.

When explicitly authorized to submit: recheck latest develop and existing PRs,
use a descriptive username-prefixed branch per project guidance, and follow its
commit/sign-off requirements. Significant feature work requires discussion first;
this draft deliberately stays a small documentation correction.

## LF Energy / PIVOT: do not generate a schema from examples

Pinned repository: `fledge-power/fledgepower-pivot-model`
`c00cbf776c90a3e0d0ffdeee4e6659508ba1d2cb`; read README, issue #2 and the three files
`models/pivottm`, `models/pivotts`, `models/pivottc`.

The inspected files are JSON model illustrations with namespace-like keys and
concrete values. They do not expose top-level JSON Schema keywords. This does not
establish that no schema exists elsewhere, nor authorize inventing required fields,
enums or protocol semantics from these examples. A class-generator recommendation
must first establish the authoritative schema/model definition.

Executed a small Python inspector: three documents parse and round-trip without
field/value loss, while raw validity, old-data and clock-quality indicators remain
visible. No indicator is promoted to a confirmed site role, fault, alarm or health
verdict. These example values are not protocol conformance vectors.

[Recorded evidence](../evidence/community/pivot-examples-c00cbf7-2026-11-17.json).
Reproduce after fetching the three upstream files to a directory:

```bash
python3 scripts/community/pivot_example_probe.py \
  --models /path/to/pivot-model-files --out /tmp/pivot-example-review.json
```

Use an unused output path. The result records input hashes; it does not claim a
schema validator or a complete typed Python binding. No upstream model source is
vendored. A useful proposed contribution is a minimal lossless Python quickstart
and an explicit explanation of the schema prerequisite, discussed on existing #2
before implementing a generator or new schema. No model change is proposed yet.

## Next focused work

1. Review and, if authorized, submit the Fledge documentation patch as a small PR.
2. Capture an actual delivery-plugin argument on a disposable Linux service before
   proposing runtime fixes; distinguish current develop from deployed releases.
3. For PIVOT #2, establish the maintained schema source and expected Python API
   with the existing discussion before generating classes.

Margo follow-up, Sparkplug lifecycle coverage and other communities remain in the
main worklist; do not start new protocol/control work merely to increase PR count.
