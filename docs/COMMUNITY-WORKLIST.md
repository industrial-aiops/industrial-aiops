# Community worklist

Added 2026-11-16. Maintain this list during normal project work; it does not
create a scheduled automation. All external participation below is **planned**,
except the Margo evidence already recorded in this repository. No paid membership,
registration, outreach or upstream submission is implied by this list.

## Maintenance completed on main — 2026-11-16

[PR #299](https://github.com/industrial-aiops/industrial-aiops/pull/299) is merged.
The IGEL source demo now uses the 0.34.1 baseline, both OPC UA installation extras
require pyOpenSSL >=26.4, and five local CA-chain/CRL checks are included. These
changes are on main; they are not a new published package release. All six PR CI
checks passed, including the Python 3.11/3.12 gates and Linux integration contracts.

First research and experiment: [entry-point report](community/2026-11-16-entry-points.md).
PR #300 merged on 2026-11-17: the parent-death refusal is now on main, still
unreleased. Next: Fledge notification context and a full delivery-plugin capture. Keep Margo
state-retention follow-up active. Vendor PKI, CRL provenance checks, IGEL/AGNES and
physical-device validation remain open; community registrations remain planned.

## First experiment — 2026-11-16

Independent Tahu helper payloads reproduced an iaiops parent-node-death cache gap;
regression and fix landed on main in PR #300; no new package release was made. No upstream defect is attributed to
Tahu. Its default-timestamp behavior was also reproduced, but existing PRs #398/#472
already cover it. Other projects have source-backed candidate tasks, not verified
integrations. See the report for exact sources and evidence limits.

## Fledge progress — 2026-11-17

[Local probe report](community/2026-11-17-fledge-notification.md): five actual C++
reason-enrichment cases passed at the pinned notification-service revision.
Current source already attaches evaluation data under `reason.data`; the missing
value claim was not reproduced at this function boundary. Full service/plugin and
version-specific validation remain pending. A comment draft is prepared, not sent.

## Concrete contribution drafts — 2026-11-17

[Fledge patch and PIVOT experiment](community/2026-11-17-contribution-drafts.md).
A Fledge delivery-guide patch now applies cleanly to pinned develop and its added
RST fragment renders. Submitted as Fledge #1748; PIVOT findings were posted to existing #2. Three PIVOT example files
round-trip in Python with raw quality/time indicators preserved; they are not
assumed to define a JSON Schema. No model API/key was needed for this work.

## Working routine

- Pick one small item per maintenance session, after immediate product defects.
- Read current upstream issues/release notes and record source URL, date and commit.
- Look for a concrete problem affecting users of both projects. Check for existing
  work before duplicating it; do not manufacture issues for visibility.
- Reproduce locally with pinned versions. Separate synthetic, independent-stack,
  reference-sandbox and physical-device evidence. Keep human semantics unconfirmed.
- Record findings as: observation → reproduction → impact → proposed contribution
  → upstream feedback → next action. Prepare small tests/docs/fixes before outreach.
- Check contribution rules/licensing before copying source. Membership, compatibility
  listings and contributor status are distinct; never claim a completed integration
  or certification from a demo. External messages/submissions require explicit direction.

## Active exploration queue

| Community | Potential contribution / first investigation | Mutual value | Status |
|---|---|---|---|
| [Margo](https://github.com/margo/sandbox) | Follow sandbox #490/#491 and CTT #18/#19; reproduce upstream changes before revising our state-retention and conformance claims | Reliable stateful industrial workloads; reference deployment evidence | Existing participation; continue follow-up |
| [Eclipse Sparkplug / Tahu](https://github.com/eclipse-tahu/tahu) | Independently produced BIRTH/DEATH, stale-value, reconnect and alias/sequence cases; compare with our tap/namespace audit and identify reproducible mismatches | Data trust and cross-implementation interoperability | Research and offline Tahu replay started; fix merged via #300; expand offline matrix |
| [LF Edge Fledge](https://lfedge.org/projects/fledge/) | Inspect existing north plugins/API and examples; prototype one read-only path into coverage/incident analysis before proposing another plugin | Give existing industrial data pipelines explainable coverage and incident evidence | Function-level probe passed; full service test pending |
| [LF Energy](https://lfenergy.org/projects/) — FledgePOWER | Inspect current project status and contribution process; seek a simulator-based IEC-104/DNP3/IEC-61850 observation case using iaiops-energy | Reproducible protocol-health evidence for energy gateways | Planned; coordinate with energy repository |
| [LF Energy SEAPATH](https://lfenergy.org/projects/seapath/) | Check workload deployment/observability examples; assess a non-critical read-only collector scenario, with no protection/control claims | Understand operations evidence for virtualized substation workloads | Planned; hardware/partner evidence pending |
| [OPC Foundation open-source ecosystem](https://opcfoundation.org/cloud/) | Start with UA Cloud Library/information-model examples and certificate troubleshooting; keep suggested point semantics separate from operator confirmation | Better model interpretation, diagnostics and reproducible interop reports | Function-level probe passed; full service test pending |

Priority: deepen Margo; start Sparkplug, then Fledge. Explore energy projects
when a concrete lab case or partner appears; keep OPC UA work narrowly scoped.
This ordering is a working preference, not a promise of acceptance by any community.

## Finding log

| Date | Community / source | Observation | Evidence and limits | Next step |
|---|---|---|---|---|
| 2026-11-16 | OPC UA / local asyncua source | Existing vendor trust tests lack CA-chain/CRL scenarios | Added local strict-validator tests; independent vendor PKI and robust CRL provenance checks remain separate | Review reproducible gaps before preparing an upstream report |
| 2026-11-16 | Sparkplug / Tahu pinned Python helper | Parent NDEATH did not invalidate iaiops device-cache reads | Reproduced with external-generated payloads; local regression and fix, offline only | Merged via #300; extend lifecycle matrix; no upstream claim |
| 2026-11-16 | Tahu timestamp defaults | Reproduced equal default timestamps across two calls | Existing PRs #398/#472 found | Follow existing work; do not duplicate |
| 2026-11-16 | Fledge / LF Energy / OPC UA | Reviewed current source/docs/issues; candidate tasks recorded | No runtimes or public uploads executed | Proceed with one local bounded fixture per candidate |

Use a new row for each verified finding. Leave an unsuccessful experiment visible;
do not turn lack of data into evidence that a device or project is healthy.
