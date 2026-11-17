# Community contribution drafts — 2026-11-17

No model API or secret key was used. Following user authorization and review,
Fledge documentation was submitted as [upstream PR #1748](https://github.com/fledge-iot/fledge/pull/1748)
and PIVOT findings were posted to the [existing issue #2](https://github.com/fledge-power/fledgepower-pivot-model/issues/2#issuecomment-6946004370).
The PIVOT submission is a discussion comment, not an implementation PR. These
submissions are not accepted/merged community integrations.

## Fledge: documentation PR submitted

Target: `fledge-iot/fledge`, develop
`cf091f09fd456a767c155fc7474944dd9057c4c1` at submission review.

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

Before submission, latest develop and existing PRs were rechecked. The fork branch
is `zw008-docs-notification-context`; the commit uses wei <zhouwei008@gmail.com>
and a matching Signed-off-by. The reviewed patch and PR text above match the
submitted content. Full service/plugin and project Sphinx validation remain open.

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

1. Follow Fledge #1748 review/CI and respond with focused updates.
2. Capture an actual delivery-plugin argument on a disposable Linux service before
   proposing runtime fixes; distinguish current develop from deployed releases.
3. Follow the submitted PIVOT #2 comment; establish the maintained schema source
   and expected Python API before generating classes.

Margo follow-up, Sparkplug lifecycle coverage and other communities remain in the
main worklist; do not start new protocol/control work merely to increase PR count.
