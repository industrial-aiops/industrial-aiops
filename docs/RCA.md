# The RCA core — why it is not a black box

Industrial-AIOps' flagship intelligence layer is the **downtime root-cause copilot**
(`iaiops/core/brain/rca.py` + supporting modules). This page explains what it is and, more
importantly, **what it deliberately is not** — because in OT the reason you can trust an agent is
that its reasoning is *explainable, cited, and refuses to guess*.

## In one sentence

Given an incident **time window** plus whatever evidence a site can hand over (alarm events, tag
samples, a dataflow verdict, a machine-state series), the RCA core **correlates those cross-protocol
signals in time**, ranks candidate root causes, and emits an **evidence-cited** verdict plus an
**advisory** (human-approved, undoable) recommended action.

## The key point: the causal reasoning is deterministic math, not an LLM

The confidence and causal logic are plain, explainable Python — nothing is handed to a model to
"guess a cause":

- **Noisy-OR confidence** — `1 − Π(1 − wᵢ)`: independent evidence that agrees compounds *toward*
  (but never reaches) certainty; a single weak signal stays weak.
- **Temporal weighting (cause precedes effect)** — a signal just *before* the stoppage outweighs one
  *during* it; signals *after* onset are treated as consequences, not causes. A cause supported
  **only** by post-onset signals is not merely down-weighted, it is graded `excluded` and says why
  ("occurred 420s AFTER the onset — a cause cannot follow its effect"), because *"ruled out, and
  here is why"* and *"scored low"* are statements of different strength and only the first makes a
  plant stop spending time on that branch. The rule is narrow on purpose — every item must be timed
  and every timed item after the onset — since an exclusion is the strongest thing this module emits
  and must never rest on a gap in the data.
- **Per-site learned cause weights** (`rca_weights.py`) — from labeled past incidents, an explainable
  smoothed signal→cause precision estimator (Laplace smoothing + per-cause min-sample guard) derives
  weights for *this* plant; thin history falls back to neutral defaults.
- **Anti-hallucination** — every citation points at a signal that is **actually present** in the
  input (a real alarm source+timestamp, a real tag flag, a real dataflow verdict). When evidence is
  thin the verdict downgrades to **`insufficient_evidence`** and lists *what to collect next* — it
  does not invent a cause to look confident.

## A verdict that is also an investigation plan

A confidence says what we think. It does not say what to go and get. So every hypothesis carries
four things, not one number:

| | |
|---|---|
| **evidence** | the cited signals that support it |
| **counter_evidence** | what argues against — today, signals whose *timing* contradicts causality. A signal can support a cause by its content and argue against it by its timing; a reader shown only the first has half the picture |
| **gaps** | what is missing to raise the grade. In a plant this is usually a **field action** — a second source for a sensor, port counters for a link, a vibration signature for a bearing — not another pass over registers already collected. That is the difference from an IT investigation, where more evidence is usually already on disk |
| **next_step** | the one thing to do, wired to the loop that already exists (`iaiops case confirm`) |

### Four grades, and one that cannot be reached from the inside

`candidate` · `probable` · `confirmed` · `excluded`

**`confirmed` is reachable only from OUTSIDE the ranking.** A confidence computed from the same
evidence that produced the ranking means the ranking agrees with itself — it cannot verify it. Three
routes, all external: a **measurement**, a **reproduction** (or recovery verification), or a
**person**. The third already existed as `iaiops case confirm`; `iaiops diag rca --from-case <id>`
lets a cause somebody recorded there reach the verdict, so nobody retypes it into a second place it
can drift. A malformed confirmation is **refused, not ignored** — silently doing nothing would leave
an operator believing a verdict had been verified when it had not.

A confirmation outranks the score *and* the timing objection, and the objection is kept rather than
erased: the person may know something the log does not, or the clocks may be wrong, and the tool may
not silently pick one.

### Reliability, beside confidence

90% from a site with three recorded cases is not 90% from a site with three hundred. Every verdict
reports whether the shipped defaults or a learned site profile is in use and, when known, how many
confirmed incidents shaped it — so a reader is not left supplying that number from imagination.

## What it reasons over (it reuses the other analyzers, never re-derives them)

- `diagnose_dataflow` — localizes *which hop* lost data · `tag_health` — ranks offending tags ·
  `subscription_health` — sequenced-feed loss/reorder
- `alarm_flood` (ISA-18.2) — flood/chattering episodes · `downtime_events` — stoppage segmentation
- `baseline` — conservative change-log band violations · `dataquality` — trust scoring
- **optional historian read** (`rca_history.py`) — with a `historian:` config, pulls the 2-hour
  pre-incident window as one more *cited* evidence class (strictly additive; without it, output is
  byte-identical, test-proven)

## Modules

| Module | Role |
|--------|------|
| `iaiops/core/brain/rca.py` | correlation + scoring engine (`downtime_root_cause`) |
| `iaiops/core/brain/rca_collect.py` | live evidence auto-collection (`downtime_root_cause_live`) |
| `iaiops/core/brain/rca_history.py` | pulls the pre-incident historian window as evidence |
| `iaiops/core/brain/rca_weights.py` | learns per-site cause weights from labeled incidents |
| `iaiops/core/brain/rca_graph.py` | re-projects a finished verdict into a causal graph (a view, not a new layer) |

## Causal-graph export (a view of the verdict, not a new reasoning layer)

The verdict is *flat* — ranked `hypotheses`, each with cited `evidence`. That is
perfect for a report but awkward for a UI that wants to draw the **signal → cause →
downtime** chain. Passing `include_graph=True` to `downtime_root_cause` (or
`downtime_root_cause_live`, or `downtime_triage`) attaches a `graph` block that
**re-projects the already-computed verdict** — it runs no new correlation, scoring,
or inference. Omit the flag and the output is byte-identical to before.

```jsonc
"graph": {
  "nodes": [
    {"id": "signal:alarm:M1_DRIVE", "kind": "signal", "label": "M1_DRIVE", "score": 0.49, ...},
    {"id": "cause:mechanical_fault", "kind": "cause", "label": "mechanical_fault",
     "score": 0.72, "confidence_band": "high", "is_primary": true, ...},
    {"id": "symptom:downtime", "kind": "symptom", "label": "downtime · line1", ...}
  ],
  "edges": [
    {"from": "signal:alarm:M1_DRIVE", "to": "cause:mechanical_fault",
     "weight": 0.49, "relation": "supports"},
    {"from": "cause:mechanical_fault", "to": "symptom:downtime",
     "weight": 0.72, "relation": "attributed_to"}
  ],
  "mermaid": "flowchart LR\n  ...",
  "meta": {"verdict": "root_cause_identified", "primary_cause": "mechanical_fault", ...}
}
```

Every value is copied straight out of the verdict, which is what makes the graph
**faithful by construction**:

- a **`signal → cause`** edge's `weight` *is* the evidence item's contribution score
  (the proximity- and cause-weight-scaled support already in `evidence[i].weight` —
  the noisy-OR / temporal-weighting result), and its `relation` is `supports`;
- a **`cause → symptom`** edge's `weight` *is* that hypothesis's `confidence` (the
  noisy-OR aggregate the verdict already computed), and its `relation` is `attributed_to`;
- **no orphan nodes** — every node is an endpoint of at least one edge, and every edge
  endpoint is a real node;
- **nothing invented** — the set of `cause` nodes equals the verdict's hypotheses and
  the set of `signal` nodes equals the cited evidence; a thin/`insufficient_evidence`
  or input-error verdict yields an **empty** graph rather than a fabricated one.

The block also carries a ready-to-paste `mermaid` string; `causal_graph_dot(graph)`
gives the same graph as Graphviz DOT. Both are pure string renderers of the structure
above — the structured JSON is the source of truth. Because the projector only reshapes
existing numbers, it inherits the same anti-hallucination guarantee as the engine: if
the verdict did not earn a node or an edge, the graph does not draw one.

## Design stance (non-negotiable)

- **Read-first / advisory only** — the core never writes and never executes. It *proposes* a
  reversible, change-managed (MOC) action; a human approves it, and a separate HIGH-risk-tier write
  tool performs it with undo capture.
- **Pure / injectable** — it analyzes *provided* evidence, so it is fully testable without a live
  plant.

## Where an LLM fits (and where it does not)

The RCA scoring is math. An **LLM appears only at the outer layer**: the copilot is exposed as
governed **MCP tools**, and an LLM agent *drives* them — chaining the analyzers, following the
`insufficient_evidence` "collect next" hints, and phrasing the **already-cited** verdict in natural
language. An optional **on-box local model** (e.g. Ollama, see the LLM adapter) can play that outer
role for a **fully air-gapped** deployment (full guide: [`AIRGAP.md`](AIRGAP.md)) — but it never
derives the causes. That separation —
deterministic, cited reasoning underneath; optional local narration on top — is exactly why the RCA
core is safe to put on a plant floor.
