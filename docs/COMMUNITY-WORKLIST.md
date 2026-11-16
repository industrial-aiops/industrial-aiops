# Community worklist

Added 2026-11-16. Maintain this list during normal project work; it does not
create a scheduled automation. All external participation below is **planned**,
except the Margo evidence already recorded in this repository. No paid membership,
registration, outreach or upstream submission is implied by this list.

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
| [Eclipse Sparkplug / Tahu](https://github.com/eclipse-tahu/tahu) | Independently produced BIRTH/DEATH, stale-value, reconnect and alias/sequence cases; compare with our tap/namespace audit and identify reproducible mismatches | Data trust and cross-implementation interoperability | Planned; first new community focus |
| [LF Edge Fledge](https://lfedge.org/projects/fledge/) | Inspect existing north plugins/API and examples; prototype one read-only path into coverage/incident analysis before proposing another plugin | Give existing industrial data pipelines explainable coverage and incident evidence | Planned |
| [LF Energy](https://lfenergy.org/projects/) — FledgePOWER | Inspect current project status and contribution process; seek a simulator-based IEC-104/DNP3/IEC-61850 observation case using iaiops-energy | Reproducible protocol-health evidence for energy gateways | Planned; coordinate with energy repository |
| [LF Energy SEAPATH](https://lfenergy.org/projects/seapath/) | Check workload deployment/observability examples; assess a non-critical read-only collector scenario, with no protection/control claims | Understand operations evidence for virtualized substation workloads | Planned; hardware/partner evidence pending |
| [OPC Foundation open-source ecosystem](https://opcfoundation.org/cloud/) | Start with UA Cloud Library/information-model examples and certificate troubleshooting; keep suggested point semantics separate from operator confirmation | Better model interpretation, diagnostics and reproducible interop reports | Planned |

Priority: deepen Margo; start Sparkplug, then Fledge. Explore energy projects
when a concrete lab case or partner appears; keep OPC UA work narrowly scoped.
This ordering is a working preference, not a promise of acceptance by any community.

## Finding log

| Date | Community / source | Observation | Evidence and limits | Next step |
|---|---|---|---|---|
| 2026-11-16 | OPC UA / local asyncua source | Existing vendor trust tests lack CA-chain/CRL scenarios | Added local strict-validator tests; independent vendor PKI and robust CRL provenance checks remain separate | Review reproducible gaps before preparing an upstream report |

Use a new row for each verified finding. Leave an unsuccessful experiment visible;
do not turn lack of data into evidence that a device or project is healthy.
