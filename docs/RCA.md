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
  *during* it; signals *after* onset are treated as consequences, not causes.
- **Per-site learned cause weights** (`rca_weights.py`) — from labeled past incidents, an explainable
  smoothed signal→cause precision estimator (Laplace smoothing + per-cause min-sample guard) derives
  weights for *this* plant; thin history falls back to neutral defaults.
- **Anti-hallucination** — every citation points at a signal that is **actually present** in the
  input (a real alarm source+timestamp, a real tag flag, a real dataflow verdict). When evidence is
  thin the verdict downgrades to **`insufficient_evidence`** and lists *what to collect next* — it
  does not invent a cause to look confident.

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
role for a **fully air-gapped** deployment — but it never derives the causes. That separation —
deterministic, cited reasoning underneath; optional local narration on top — is exactly why the RCA
core is safe to put on a plant floor.
