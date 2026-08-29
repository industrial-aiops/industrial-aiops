# Changelog

## 0.25.0 — 2026-08-29

**A walkthrough and two third-party servers.** Nothing here was found by the test
suite, which was green before and after every one of these. They came from
installing 0.24.0 from PyPI and following the README against a real Modbus line,
and from putting somebody else's protocol implementation on the other end.

### Added

- **`iaiops oee measure --since` / `--until`** (#226). The flagship number could
  only be measured over an endpoint's ENTIRE stored history. Two collection runs
  fifteen minutes apart, and the idle gap between them counted as one blind span:
  the second run's own coverage was 76.84%, the measurement reported 46.75% and
  refused. A site assessing in March and again in August could measure neither.
  `investigate open` already took `--start` / `--end`; the flagship figure did not.

  **The window is charged for in full.** Its unsampled head and tail count as
  blind exactly like a gap in the middle, so narrowing the question to the
  minutes that happen to have data cannot raise your coverage — asking about a
  shift you observed a tenth of returns a refusal, not "100% of what we saw".
  Without that half the option would have been a fresh way to produce the
  flattering answer this product exists to refuse.

  The window is authoritative inside the engine (samples outside it are dropped
  even if the caller forgot to filter), it scopes the production count with the
  same bounds — the two figures are a ratio and must agree about which seconds
  existed — and it is stated in the CLI heading and in the report header rather
  than only in a note. With no window, both say so.

### Fixed — what the tool said about the plant

- **`iaiops scan` on EtherNet/IP uploaded the controller's entire symbol table**
  (#220). The identify probe is named `eip_list_identity` and its rationale
  promises a CIP identity read; it opened a `pycomm3.LogixDriver`, whose
  `open()` ends in `get_tag_list(program="*")` — every tag, program-scoped
  included — under a signed preview that says "one minimal in-spec read per
  candidate" and "never walks an address space", recorded as one wire event.
  Measured against a third-party stack: **6 requests / 324 bytes → 3 / 76**. The
  same call also failed on every non-Logix device, so drives, I/O adapters and
  gateways were reported as an open port with no vendor.
- **A tag at address 0 was deleted in silence** (#214). `ref: 0` is falsy, fell
  through the alias chain to `""`, and the entry was dropped — then `readiness`
  reported the missing role as something the SITE had not supplied. Zero is an
  ordinary Modbus register, coil, S7 DB offset and MC/FINS address. A tag with
  no address is now refused, naming the endpoint and the position.
- **A scan told the customer their host speaks no protocol we support** (#215)
  after trying six ports. `iaiops modbus holding` read that host's registers a
  minute later. The note now names the ports tried and says the set is never
  widened.
- **…and a host that was never probed is not a host that refused** (#223).
  Pointing #215's new wording at a real /24 produced "ALIVE but refused every
  port this scan tried (none)" — the sweep had aborted after 50 consecutive
  failures and those hosts were known only from ARP. The two populations are now
  separate, and nothing is claimed about what an unprobed host speaks.
- **MTConnect: the agent's own health could be reported as the machine's**
  (#219). A real agent streams its own `Agent` device, `AVAILABLE` whenever it
  answers; the snapshot picked data items by type across the whole document. A
  stopped machine could read as available. Now scoped to one device, with a new
  optional `device:` on the endpoint and a refusal when an agent serves several.
- **MTConnect `UNAVAILABLE` is no longer `down`** (#219). That word is the
  agent saying it has no valid value, usually a disconnected adapter — not a
  stopped machine.

### Fixed — what the tool said about itself

- **There was no way to ask the tool what version it is** (#222). Not
  `--version`, not a `version` command, not `doctor` — so the opening question
  of every support conversation was unanswerable from the product, on boxes that
  are usually air-gapped. `--version` / `-V` prints one parseable line, and
  `doctor` now leads with the version and the Python under it, because that
  output is what a site pastes into a support thread.

- **A successful `collect run` ended by warning that it took too long** (#216).
  The 300s governance timeout is a hang detector; this command's runtime is the
  request, and `--duration 7d` is the documented workflow. Commands may now
  declare their own ceiling; everything else keeps the hang detector.
- **A clamped OEE factor now says so where the number is** (#218):
  `Performance 100.0% (clamped from 494.0%)`. The raw value was already in the
  warning below, but the factor block is what gets read aloud.
- **A stored investigation summary stopped mid-word** (#217) — the OT-value
  sanitizer applied to composed prose. The bound stays; the cut lands on a
  clause and is marked.
- **`readiness`'s docstring pointed at an empty module** (#213) for "the live
  producers of `expressible=False`"; #204/#207 removed the last two.
- **The router skill mentioned nothing from 0.24.0** (#212), and the first fix
  for it broke two guards — one by rewording the sentence a guard was anchored on.

### Fixed — the forwardable reports

Both found by opening the generated HTML and looking at it, not by reading code.

- **A clamped OEE factor rendered as a full green bar** (#225). #218 marked the
  clamp in the CLI; the HTML report — the file that actually gets forwarded —
  still drew Performance at the ceiling with no marker, which is the strongest
  "everything is perfect" signal a page can send. The meter and its accessible
  name now say `clamped from 3726.0%`.
- **A clean scan report numbered its sections `1 · 2 · 4`** (#225). The
  diagnosis section renders nothing when there are no notes and no per-host
  errors, and the numbers were typed into each heading — so the BEST possible
  result produced the most suspicious-looking document, on the artifact whose
  whole job is to be checkable against a packet capture.

### Verification

- **MTConnect → rung 2a**: `scripts/mtconnect_agent_harness.sh` +
  `tests/test_mtconnect_agent_live.py` run against the MTConnect Institute's own
  `cppagent`. Still not covered: a connected adapter, so no live SAMPLE has been
  decoded.
- **EtherNet/IP identification → rung 2a**: `scripts/enip_simulator_harness.sh`
  + `tests/test_discovery_eip_live.py` against `cpppo`. The Logix tag layer
  stays 2b — cpppo implements no Logix objects — and physical gear stays rung 3.

## 0.24.0 — 2026-08-28

**The investigation, end to end — and the input path that was missing under it.**

An investigation is now an object with eight evidence steps rather than a single
command, and every step says whether a gap is something **you** have not supplied
(naming the command that would) or something **this product** cannot express at
all. Those two send a person to entirely different places.

Underneath it, the thing that has really been blocking sites: **there was no
usable way to tell the product what a tag MEANS.** HLD §10.1 named a
point-list confirmation sheet and nothing was ever built for it, so the only
route was hand-editing `role:` in config.yaml — exactly the method §10.1
says stops working at a hundred rows. `iaiops tags export|apply|page` is that
route.

Both fronts of the architecture's own claim are closed too: `investigate`,
`relations`, `knowledge` and `readiness` had all shipped **CLI-only** while the
HLD and the README both said *two front-ends, one engine*. 182 governed tools.

And five defects found by walking a demo through two lab VMs rather than through
mocks — the sharpest being a root-cause analysis that diagnosed a **sensor fault
at the plant** when the endpoint had merely been switched off, and grew *more*
confident the more tags you asked about.

### Fixed — the Chinese README was missing everything built this week

`investigate`, `relations`, `knowledge` and `tags` had **zero** mentions in
`README.zh-CN.md`. The English half was written; the Chinese half was not. Same
shape as the gap #205 closed — a capability with one way in — one level up.

Both now carry the same sections, and the capability table gains the row that was
missing entirely.

### Fixed — a README that taught a command which does not exist

`iaiops modbus detect-byte-order` has been in the Chinese README for several
releases. `modbus_detect_byte_order` exists — **only as an MCP tool**. There is
no such CLI command, so a reader following the README got an error. Same shape as
every gap found this week, pointing the other way.

### Added — a gate so that cannot happen again

`test_readme_commands_exist.py` extracts every `iaiops <group> <command>` from
the shell blocks of both READMEs and resolves it through Typer — 55 invocations
guarded. Resolved through Typer rather than grepped, because a command that is
defined but never registered would pass a grep and still fail for the reader.

Its own first version reported `iaiops is designed` — an English sentence that
began a line — which is how a guard like this loses its credibility, so
extraction is scoped to fenced shell blocks and a test asserts the finder matches
something at all.

### Added — `iaiops tags page`, the App front end as one static file

HLD §13.9's last front end, and its narrow justification: the App page exists for
the steps where a person must go **row by row and tick** — point-list
confirmation, timeline review. Not a dashboard.

Delivered as a file, not a served app. A localhost server inside an OT box has to
answer which address it binds, who authenticates and how the firewall is opened —
and every declaration in this product requires `--by`, so **a page with no
identity cannot record who ticked a row**, which is the one thing the step exists
to capture. The page collects; the author is supplied at `tags apply`, where the
refusals already live.

**It re-implements no refusal**, and a test asserts that: `run_state` needing
`running_when`, a ref having to be monitored, a role claimed twice — reproducing
any of those in JavaScript is how they drift from the ones that gate the config,
and a page that says "looks fine" while `apply` refuses is worse than no page.
The role options come from `TagRole.ALL` at render time for the same reason.

It ships script, unlike the investigation and OEE reports. What stays true is the
property that matters in a plant: **no network request**, data embedded rather
than fetched. Embedding is in a JavaScript context rather than HTML text, so a
tag label containing `</script>` would end the block early — every `<` is emitted
as `\u003c`.

### Fixed — two editable cells, one of them pre-filled

Found by looking at the rendered page. `running_when` was echoed into its
**editable** input while `role` was left blank, so somebody who changed that row
to a counter got refused over a field they never touched. Everything already
declared is now read-only context (`run_state (running_when: 2)`), and everything
editable starts empty — in the exported CSV too.

### Fixed — a hardcoded column order in code no test runs

The page's CSV builder is JavaScript, which pytest never executes, and it named
its fields in order. A reordering of `SHEET_COLUMNS` would have shifted every
value one column right with nothing to catch it. It now maps over
`SHEET.columns`, and a test pins that it does.

### Added — `iaiops tags export|apply`, the point-list confirmation sheet

HLD §10.1 named this and then nobody built it: point-list semantic confirmation
is naturally a table, and *the CLI need only export a CSV, let a person edit it,
and import it back*. The App page was ordered "after" — and this, the CLI
fallback it was supposed to rest on, **did not exist either**. Until now the only
way to say "this tag is the production counter" was hand-editing `role:` in
config.yaml, which is exactly the method §10.1 says stops working at a hundred
rows. That is what "the semantic layer still has to come from a person" has
really been blocked on: not a design gap, no usable way to supply it.

The `role` column is exported **empty**, including beside a tag called
`GoodPartsCounter`. A name is not a declaration.

**It emits a config patch instead of storing its own declarations, and the first
version got that wrong.** Roles were stored as `declared` facts with an author,
the way `relations declare` and `knowledge mount` do. The coupling that makes it
wrong here: `oee measure` reads `role` off the config tag OBJECTS, and
`MonitorTag` refuses a `run_state` that carries no `running_when`. A parallel
store would have let `readiness` report the mapping as met while `oee measure`
still could not run — the flattering error this product keeps having to remove.

### Fixed — a patch that re-parsed into something that matched nothing

`ref: 40001` came back from YAML as an **int**, while a tag's `ref` is a string,
so a pasted patch annotated no tag at all. Every assertion about the patch text
passed while the patch was unusable; the round-trip test — merge it into a real
config, load it with the real loader, assert `readiness` changes its mind — is
what caught it. Refs are now emitted JSON-quoted (YAML 1.2 is a JSON superset).

### Added — `investigate --report`, the file that gets forwarded

§13.9's front-end table orders these: CLI **first**, the self-contained HTML
report **alongside it**, the App page after, MCP **last**. The last one got built
first (#205/#206) and this — ordered ahead of it — was skipped. `scan` and
`oee measure` could both put their answer on paper; the investigation, which is
what an integrator actually hands to a plant, could not.

`investigate plan|open|show --report x.html [--lang zh]`. Self-contained: no CDN,
no font, no image, and no `<script>` at all — "this file runs nothing" is true
here by construction, not by policy.

**Deliberately unlike `oee measure --report`, which refuses to write for a refused
measurement.** That is right for OEE: the report is a number, so a file existing
at all asserts one was measured. This report's content is *how far this got and
what each step still needs*, which makes the blocked case the one most worth
handing over — for a site nobody has instrumented, it is the entire deliverable.
Copying the OEE guard across would have deleted the most useful output for exactly
the sites that need it.

What it must never do is let a blocked investigation look finished, so the
headline is the walk (`2 / 8`) and no step's own words may appear above it. The
first version of that test asserted "2" and "8" appeared near the top — which
every step number also satisfies; deleting the progress figure outright left it
green. Rewritten to pin the element and the document order, four mutations now
fail it.

### Fixed — a gap list that repeated one action four times

Found by reading the rendered page, not by an assertion. On a bare site the
"what to supply next" section listed eleven gaps, four of which were `collect
run` under four different step numbers — in a list whose own lead sentence says
it is ranked by where the walk stops.

Deduping by requirement key was the obvious move and changed nothing: those four
steps want four differently *named* things ("collected samples", "samples to
check", "a sampled series", "evidence to rank") that one command supplies. It
now groups by **action**, so that reads `2, 3, 5, 6, 8. collected samples in the
local store`. Inexpressible requirements have no action by definition and still
group by key, or every "this product cannot accept it" in a report would collapse
into one line.

### Added — `site_readiness`, the last CLI-only command (§3.1)

The previous entry gave the investigation layer its MCP tools and said in its own
first paragraph that `readiness` had the same gap — then left it there rather
than smuggling an unrelated change into that PR. This closes it.

`site_readiness` is the companion to `protocols_supported`, one altitude down:
that one says what the product can do, this says what **this installation** can
do. An agent that calls the first without the second plans a scenario the site
has no inputs for. It contacts nothing — derived from `config.yaml` and the local
store — so it runs against a site nobody has authorised anyone to probe.

It recomputes nothing: the test asserts the tool's output is the engine's
`as_dict()` **verbatim**, not merely equivalent. `readiness`'s own engine test has
carried `test_the_report_serializes_for_a_second_front_end` since the day it was
written; the second front end just did not exist.

What the tests actually guard is the gap-reporting, since that is what `readiness`
is for: that `blocked_on` (the ranked "supply these first") survives, that the
"nothing was contacted" note survives, and that the `db` argument really routes —
accepting `db` and ignoring it would have passed every other assertion while the
tool answered about a different site. Three mutations confirm each is load-bearing.

### Fixed — a docstring asserting a limit its own code had removed

`iaiops/core/readiness/assess.py`'s module docstring still said the OEE role
mapping was **inexpressible** ("there is no way to supply this"). `role:` made it
expressible, and `_oee_mapping_req`'s own docstring records that — the paragraph
above it went on claiming the product was worse than it is. It now points at
`iaiops.core.investigate.steps`, where the live `expressible=False` producers are.

### Added — the investigation layer on the MCP front end (§3.1)

`iaiops investigate` / `relations` / `knowledge` — and `readiness` before them —
had shipped **CLI-only**, while §3.1 and the README both claimed *two front-ends,
one engine*. The claim sat there and nothing checked it. Same shape as every gap
this repo keeps finding: the capability exists, one of the two ways in does not.

Eight tools, all delegating to the same functions the CLI calls —
`investigation_readiness`, `investigation_open`, `investigation_show`,
`investigation_list`, `line_relation_declare`, `line_relations_list`,
`mechanism_library_check`, `mechanism_library_list`.

The tests are mostly about **agreement**, because a tool that computes a
plausible answer of its own is worse than a missing one: it lets the two
front-ends drift while both look healthy, and nothing marks where they diverged.
They assert the same `reachable_through`, the same per-step statuses, the same
refusals (a cycle, a missing author, `nothing_known` rather than "cleared"), and
that a relation declared through the tool is visible to the engine — the proof
that it is one store and not two.

Two guards fired on the way in and both were right:

* **The tool-flood threshold** (135 → 150). `factory` now exposes 143 tools, and
  a threshold that warns on every legitimate launch is one nobody reads. The
  invariant it protects — largest named edition ≤ threshold < `all` — still holds.
* **The `[WRITE]` tag contradicted the derived `readOnlyHint`.** I had tagged
  `line_relation_declare` `[WRITE]` from first principles. In this repo `[READ]`
  means *does not write to a device* — `baseline_record_change` and
  `adopt_alias_map` are the same shape — and `readOnlyHint` is derived from risk
  level, preview mode and egress, not from local writes. The convention is the
  repo's; my test was rewritten to assert it, and the docstring still says
  plainly that it writes.

### Fixed — the README omitted every command added this week

`investigate`, `relations` and `knowledge` had **zero mentions in either README**,
which is exactly the omission caught before the 0.23.0 release and repeated. The
English README now documents the eight-step walk in the place a reader reaches it
— after the case loop, where it sits on the customer's path. Both tool counts
corrected (English 173 → 181; the Chinese one still said 166, one release behind
even before this work).

### Added — `iaiops knowledge mount`: the knowledge slot, and the last product-side hole

HLD §13.10 delivery step 4. Step 07 asked whether a candidate cause is even
possible on this equipment; until now the honest answer was *"this product
offers no way to tell you"*, because fault mechanisms were hardcoded constants
with no slot at all.

**The shape comes from what the field standardised.** ISO 14224 keeps three
levels apart, and this repo's seven `CAUSE_KEYWORDS` collapse all three into one
word:

| level | meaning | example | answers |
|---|---|---|---|
| failure **mode** | the observed effect | reading frozen | what you SAW |
| failure **mechanism** | the physical process | transmitter drift | what to go and CHECK |
| failure **cause** | the root condition | `sensor_fault` | what to FIX |

**Seven top-level causes is the right number and a library does not add to
them.** Practitioner consensus is blunt: past roughly forty codes two operators
stop picking the same one and the data degrades. Entries attach to the taxonomy
the learner already speaks. (The commercial libraries of tens of thousands of
failure codes are for machine-emitted codes, where nobody has to choose — a
different layer.)

Four refusals, in order of the damage each would do:

1. **Silence is not agreement.** Nothing known about a candidate reports
   `nothing_known`, never "no objection". A knowledge base that has never heard
   of a cause has not cleared it, and that reading would make the step worse
   than not having it.
2. **It may exclude, never confirm** (D28/D29). Applicability constraints rule a
   candidate out — the strong move a ranker cannot make. `confirmed` still comes
   only from outside the ranking.
3. **Every entry names its source.** A mechanism with no source is
   indistinguishable from a guess a year later.
4. **All-or-nothing mounting.** A half-mounted library is one nobody can reason
   about.

The exclusion is not theoretical. This morning's RCA defect diagnosed
`sensor_fault` on a Modbus endpoint that was merely switched off; a library
saying *"every sensor_fault mechanism here needs HART or OPC-UA"* rules that out
on applicability alone, before any evidence is weighed.

### Changed — the eight-step map has no product-side holes left

With relations, the timeline and the mechanism library, **every remaining gap in
`investigate plan` is something a site can supply** — no alarm source, nothing
collected, nothing mounted. No step reports "this product cannot do it".

That is a good state and a dangerous one to leave untested: `Requirement.
expressible` went years with **no producer at all**, which is how its render
branch stayed dead and unnoticed. Both flags now have tests on the **machinery**
rather than on any particular gap, ready for the next thing the product
genuinely cannot express.

### Added — declared line relations, and the timeline they unlock

HLD §13.10 delivery step 3, in two halves.

**`iaiops relations declare <upstream> <downstream> --by <you>`** — the second
axis of root-cause analysis (§10.3②). With time alone, an upstream stoppage
produces a string of equally-confident downstream false causes, because on a
line downstream co-occurrence is *guaranteed* whatever the cause. That guarantee
is exactly why this is a declaration and not a detector (D25): a person stating
the line order needs no inference. Stored as `declared` facts, isolated per site
(D34), and refusing self-loops and cycles at declaration time — where somebody
can still fix them — rather than at analysis time.

This is also the **first thing to close an `expressible` gap**. `investigate
plan` reported cross-asset propagation as "this product offers no way to supply
it yet", which was true. It now reports it as an ordinary unmet requirement with
the command that satisfies it. A flag left set after the gap closed would stop
meaning anything.

**Step 05, the timeline** (`core/brain/timeline`) — Trigger · Symptom ·
Propagation · Recovery, fenced so it stays a re-ordering rather than a story:

* every entry cites the evidence id it came from, and nothing is interpolated
* **propagation follows only declared relations**, and only forward in time —
  a declared edge alone would launder any co-occurrence into a causal claim
* the four labels need a **declared run-state tag**; without it the step returns
  an ordered change list and says why, rather than guessing which value means
  running
* with no relations it degrades to a single-asset timeline **and says so**

Three things the real data taught, none of them visible from the tests alone:

* **A counter is not a timeline of events.** Measured on the cross-LAN
  collection: run state changed on 2% of its samples, the two production
  counters on 77%. Treating "the value changed" as an event made every sample an
  event — 500 entries, cap hit, the actual trigger buried under 361 "symptoms".
  Tags that change on more than half their samples are excluded **and named**.
* **A window that opens already stopped has no trigger in view**, and saying so
  ("widen the window") is more useful than an unlabelled list. Without that
  check, the first transition found is the *recovery*, labelled as the trigger.
* **Truncation is announced.** A partial timeline that does not say so reads as
  a complete one, and the part it drops is the later part — where a recovery
  lives.

### Added — `iaiops investigate open/show/list`: the investigation as an object

HLD §13, delivery step 2. `plan` answers "how far COULD we get here"; this walks
the eight steps over a **real window** and records what each one produced. It is
persisted, so it can be re-read and advanced later — that is what makes it an
object rather than a command (D31).

**It adds no analysis.** Each step calls something that already exists
(`query_samples`, `historian_health`, `downtime_rca`, the `case` loop) and
records the outcome, in one of three states:

* **done** — it ran, here is what it found
* **refused** — it could not run *here* (no samples in the window, no alarm
  source on this endpoint); a site fact, usually fixable
* **not possible** — *this product cannot do it at all yet*; nothing the
  operator does will change it

Against the real cross-LAN collection: 3 of 8 steps, 04 refused for a site
reason, 05 and 07 not possible for a product reason.

Two corrections during implementation, both caught by running it on real data
rather than by reading it:

* **Step 3 reported "0 gaps" over a window with a genuine 13-second outage.**
  `historian_health` defaults to a 60 s gap threshold, and this collection ran
  at 200 ms. The threshold now comes from the window's own cadence, using the
  `GAP_FACTOR`/`GAP_FLOOR_S` rule `oee_measure` already measured against a real
  device. It finds the outage.
* **It also reported a "6 ms cadence" for a run that sampled every 200 ms.** The
  store interleaves tags, so the median interval of the *mixed* series is the
  spacing between tags, not the sampling rate — off by thirty times, in the
  direction that makes the data look finer-grained than it was. Each tag is now
  checked against its own cadence. Reports 220 ms, which is the real rate plus
  round-trip.

And one refusal that had to be added: **the ranking step used to claim "no
candidate cause is supported"** while being handed a raw sample series with
every point marked good. `downtime_rca` reads alarms, a dataflow verdict and
quality flags; a series has none of them. "We looked and found nothing" when the
truth is "we handed it nothing to look at" is the same error the RCA copilot
made this morning, pointed the other way. It now refuses and names what would
make it runnable.

**HLD §13.9 corrected in the same commit**: persistence does not go through the
site knowledge base. A `KnowledgeBase` is an append-only set of *facts*; an
investigation is a mutable record of an *activity*. `core/collect/session.py` is
the precedent that fits.

### Added — `iaiops investigate plan`: how far an investigation could get here

HLD §13, delivery step 1. `readiness` answers "which scenarios can this site run
today"; this answers the next question down — **if something stopped tomorrow,
how many of the eight evidence steps could we actually walk**, and for each one
we could not, what is missing.

Contacts nothing: no device, no network, no historian, same as `scan plan`. That
is what makes it runnable on a site nobody has authorised you to probe yet —
which is the site that most needs the answer.

The report distinguishes three things a single "missing" would blur:

* **blocked** — you have not supplied it, and here is the command that would
* **degraded** — it runs without this, and here is what you lose
* **not yet possible** — *this product offers no way to supply it at all*

That last one made `Requirement.expressible` real. The field, its serialization
and a CLI branch to render it had all existed since `readiness` was written —
**with no producer anywhere in the codebase**, so the line "this product offers
no way to supply it yet" had never printed. It was also unreachable twice over:
the branch was nested under `if req.fix`, and an inexpressible requirement has
no fix by definition. Both fixed; `readiness` renders it correctly now too.

Two steps report it today, for different reasons: cross-asset timeline
propagation needs declared line relationships (D25 — there is no command to
declare them), and the knowledge check needs a mountable fault-mechanism library
(§13.8 — mechanisms are hardcoded constants and there is no knowledge base).

`reachable_through` is a **walk**, not a count of unblocked steps. On a
Modbus-only line the two differ — the walk reaches 3, the count says 6 — and
only the walk answers the question. Steps blocked further along are reported
separately, so a gap at step 7 does not read as the reason the walk stopped at 3.

### Fixed — the RCA copilot turned its own blindness into a fault at the plant

Found by running the flagship command the way a plant would — *"the line stopped
this morning, tell me why"* — against an endpoint that was **switched off**,
which is the ordinary case: the incident is over and nobody has powered the cell
back up.

Every read failed with `Connection refused`. `_sample_tag` filed each failure as
a bad-quality sample (its comment said so: *"a per-read failure is bad-quality
data"*), and the verdict came back:

```
primary_cause: sensor_fault, confidence 0.70
recommended_action: Field-verify the sensor/transmitter and wiring.
```

The sensors were fine. **It knew** — `dataflow_verdict` was already
`cannot_connect` and `comms_loss` was a candidate at 0.60. It lost, because a
dead transport manufactures one bad-quality signal **per requested ref** while
the truth gets a single dataflow signal:

| refs | primary | sensor_fault | comms_loss |
|---:|---|---:|---:|
| 0 | comms_loss ✓ | 0.0000 | 0.6000 |
| 1 | comms_loss ✓ | 0.4500 | 0.6000 |
| 2 | **sensor_fault ✗** | 0.6975 | 0.6000 |
| 3 | **sensor_fault ✗** | 0.8336 | 0.6000 |

Confidence that the plant's sensors are broken, as a function of how many tags
you asked about. That monotonicity is the proof it was an artifact.

The fix is at **collection**, not scoring: a read the device never answered is
not handed on as evidence, and the refs are named under `unreadable` instead —
dropping them silently would leave the operator believing those tags were
examined and found innocent. `refs_sampled` now counts what was obtained rather
than what was attempted. A device that **answers** with a bad value still
produces real `sensor_fault` evidence, and `downtime_rca` is untouched, so a
hand-authored bundle scores exactly as before.

Verified against the switched-off lab endpoint: `sensor_fault` is 0.0000 at
every ref count, the verdict is `comms_loss`, and the recommended action is to
check the network path rather than to field-verify wiring. Four mutations
checked.

### Fixed — the live TSDB tests leaked a database on every run

Found on the lab TDengine while verifying the three fixes above: five leftover
`iaiops_tr_*` databases had accumulated, and the server began refusing writes
with `[0x03BA] Vnodes exhausted` — twice, presenting as an unrelated product
failure mid-way through an unrelated verification.

Not flaky teardown. `test_tdengine_round_trip_over_a_libtaos_free_transport`
built its database name **inline with no cleanup at all**, leaking one per
transport parameter, every run. It could not use the existing
`tdengine_database` fixture because that one cleans up through the **native**
client and would skip on exactly the machines the transport tests exist to
cover.

- A `throwaway_tdengine_db` fixture that drops over **any** available transport.
- A session-start sweep of scratch databases abandoned by **dead** processes, so
  one crashed run cannot poison every run after it. Its pattern is deliberately
  tight — it can never match `iaiops`, the sink's default database name — and it
  skips any pid still running, so two concurrent sessions cannot delete each
  other's data. Every uncertain case resolves toward **leaving** a database:
  a leftover costs a `DROP`, a wrongly-dropped one costs the data.
- A session-**end** check that names anything this run left behind. A leaked
  database is invisible to the suite — the run that leaked five of them was
  green every time — so the leak now reports itself while the change that caused
  it is still on screen.

Verified against the live lab server: a planted leftover with a dead pid was
swept, a same-shaped decoy under a different prefix and an unrelated `rcatest`
were untouched, and a full run now ends with nothing of ours on the server.
Removing the teardown reproduces the leak exactly (two databases, one run).

### Fixed — the historian had no reachable write path

Found by walking the shipped demo through two lab VMs: the Modbus device on one
machine across a real LAN, TDengine and IoTDB on another. Collection worked;
every documented route from "I collected data" to "it is in my historian" was
broken, in three independent places.

- **`iaiops export json`** — a new export format, and the missing link. `push
  --input` consumes a JSON list of points; the existing formats (csv / sqlite /
  parquet) are all spreadsheet-shaped, so the collected history that `oee
  measure` reads had **no supported route into a historian at all**. Its shape is
  fixed by `normalize_points` (`tag`→`metric`, `ts`→`timestamp`) rather than
  chosen, because a straight dump of the store row is rejected with "No usable
  points to write" — a file that looks right and is silently useless.
- **`iaiops historian push --transport native|rest|websocket`** — the flag was
  missing entirely, so push always used the native client, which needs `libtaos`
  (a vendor tarball, not a PyPI wheel). On macOS and on any air-gapped Linux
  without it, `push --sink tdengine` **could not run**. The REST and WebSocket
  transports were built and working the whole time; only the CLI could not reach
  them. Passing it to a sink that has no transport is now refused, not dropped.
- **A failed write's message is no longer cut mid-sentence.** The 200-character
  cap truncated the libtaos error at `"It is a ve"` — exactly where our own text
  starts naming the way out. Bounded at 600 now; the cap is for a client library
  echoing a query back, not for our remediation sentence. That message also names
  the CLI flag rather than only the Python keyword.
- **`docs/CHINA.md` §4** documented `iaiops modbus read-holding` — a command that
  does not exist (it is `holding`), whose output shape push rejects anyway.

Verified against the lab historians, not only in tests: 999 of 999 points from a
real cross-LAN collection run written to live TDengine over `--transport rest`
and to live IoTDB, from the same exported file with no conversion.

### Fixed — the TDengine reader returned a timestamp that was wrong or unreadable

Found the same day, pushing one cross-LAN collection run into BOTH lab
historians and reading it back. The same 999 samples came back as two different
instants:

```
IoTDB      2026-08-26T07:47:13.436000+00:00     ISO-8601, offset-aware
TDengine   2026-08-26 15:47:13.436000           naive, client-LOCAL
```

Through this codebase's own `parse_ts` — which coerces a naive stamp to UTC, by
design — those land **28,800 seconds apart**. And over the WebSocket transport it
was worse: `'2026-08-26 15:47:13.436 +08:00'` carries its offset but has a space
before it, which is not ISO-8601, so `parse_ts` returned `None` and the window
quietly held nothing.

The server was never ambiguous — asked over plain HTTP it answers
`2026-08-26T07:47:13.436Z`. The meaning was lost on our side: `taosrest` converts
the instant into the CLIENT's zone and drops `tzinfo`, and the reader forwarded
whatever arrived through `str()`.

`query`, `latest` and `coverage` now normalise to ISO-8601 UTC, matching the
IoTDB and SQLite readers. A naive value is read as client-local (which is what it
is), not as UTC. An unrecognisable stamp is passed through rather than guessed —
a visibly wrong stamp can be spotted; an invented one cannot.

Verified against the live lab TDengine over **both** `rest` and `websocket`, under
`TZ` of UTC / Asia/Shanghai / America/New_York / Australia/Sydney: one answer,
equal to the server's own. Before the fix those four returned four different
values. Five mutations checked, including the one that looks right — relabelling
a naive stamp as UTC instead of converting it.

### Fixed — the demo opened by warning about itself

`./demo/oee-line/run_demo.sh` starts with `iaiops readiness`, so the first line a
prospect saw was:

```
Security warning: /var/folders/.../.iaiops has permissions 0o755 (should be 700).
```

The warning was **right** — `mkdir -p`'s mode is masked by umask, so the demo's
own config directory landed world-readable. The product does this correctly
(`iaiops/cli/init.py` chmods both directories it creates, and
`core/governance/audit.py` carries the comment explaining why `mkdir(mode=...)`
alone is not enough); the showcase was the one place that did not.

`tests/test_demo_script.py` now **executes the shipped setup lines** rather than
restating them, so deleting the `chmod` fails the suite. It also pins that every
`iaiops` call in the demo carries the temporary `HOME` — the isolation the script
promises at the end.


## 0.23.0 — 2026-08-25

> **The release where the tool stopped needing a person to drive it.** 0.22.0 could
> read a device once, when asked. This one surveys a network you were given no list
> for, tells you which scenarios that site can run today, collects for a week
> without a resident process, measures an OEE against the figure the plant keeps by
> hand, and writes it to one self-contained file you can forward.
>
> **Nine defects in here were found by pointing the code at something real** — a
> Modbus device on a LAN, a live IoTDB, a live TDengine — and none of them were
> findable by the test suite, which was green throughout. Two more came from a
> pre-release audit that read only the code written for this release. The pattern is
> in the entries below and it is the same one every time: **a value that means "I do
> not know" rendered as a confident number**, almost always in the direction that
> flatters the tool.
>
> Everything below serves one sequence — **collect what a line actually does, turn
> that into an OEE figure honest about what it could not see, and keep what was
> learned when the raw samples are gone.**

### Added
- **`iaiops readiness` — what this site can run today, and what each gap is waiting
  for.** Every capability except `scan` assumes you already know your endpoints, and
  nothing told a new user which scenarios their site could run now. It contacts
  nothing: readiness is a judgement about configuration and stored history, so it
  answers instantly, offline, about a site nobody has authorised you to probe — which
  is the site that most needs the answer. Gaps are ranked by how much supplying them
  would unlock, and a requirement no config can express is reported as such rather
  than as merely unconfigured.
- **`iaiops collect` — bounded assessment runs that fill the local store.** OEE's
  brain existed; nothing fed it. Runs are capped at 14 days and the operator must
  state the end — there is deliberately no run-forever mode, because a resident
  process on an OT network needs change management while a laptop running for a week
  does not. Every run records the windows it could NOT see, so a gap is never
  silently readable as a stoppage.
- **Collection survives an interruption, and reports the hole it leaves.** A week-long
  run can now resume after a closed lid. The time between stopping and resuming is
  treated as a blind window exactly like a dropped connection: stitching the halves
  into one continuous series would manufacture a measurement over a window nobody
  observed, and would do it in the direction that makes availability look better.
- **Semantic tag roles (`run_state` / `total_count` / `good_count` / `reject_count`)
  and a line's `ideal_cycle_time_s`.** OEE could previously only be hand-fed five
  numbers. Roles are declared, never guessed. `running_when` closes the status-word
  trap: with the `0=stopped 1=idle 2=running 3=fault` word most PLCs actually expose,
  "any non-zero means running" counts three of four states as productive.
- **`iaiops oee measure` — availability from collected history, honest about blind
  time.** Elapsed time is sorted into three buckets — running, stopped and **unknown**
  — and the unknown one is reported, never distributed. Below 50% coverage it declines
  to give a figure. `--reported` sets the measured number beside the one the site keeps
  by hand.
- **Performance and Quality, completing the OEE figure.** Each factor appears only
  when its inputs were declared. Production counts sum positive deltas only: a counter
  that wraps or is reset at shift start looks identical in the samples (65000, then 3),
  and `max - min` across that window credits the line with ~65,000 phantom parts.
- **The site knowledge base, with provenance that cannot be laundered.** Facts carry
  `declared` / `derived` / `suggested`, and a suggested fact is withheld from
  reasoning: used as if it were declared it makes root-cause analysis confidently
  wrong, and unlike a wrong answer it compounds. An empty base is an ordinary starting
  state, not an error — the product has to be useful on a site that has entered
  nothing.
- **Cases — the loop that lets the RCA weights learn from use.** `learn_cause_weights`
  could always learn a per-site cause profile; it had no corpus it could grow, so the
  tool could run for two years and stay as clever as on day one. Capture mode is
  derived, not declared, so a cause picked from our own ranked list cannot be counted
  as independent evidence for the ranking that suggested it.
- **`iaiops case list` / `confirm` / `dismiss` — the entrance to that loop.** The audit
  trail already knows who ran what four minutes after the line stopped; showing it
  turns "what happened?" from an interrogation into a prompt.
- **`iaiops store status` / `prune` — raw samples have a lifetime, derived facts do
  not.** Measured before
  designing — three tags at 200ms is 2.0 GB a week, while a year of stop events
  derived from it is about 3 MB, a factor of 35,000. Pruning refuses to delete samples
  whose value has not been extracted, and defaults to a dry run.
- **Omron FINS is collectable.** `readiness` listed which endpoints can be sampled on
  a schedule and FINS was absent only because nothing mapped a single point reference
  onto the connector. A bare `100` is refused rather than assumed to be `DM`: `DM100`
  and `CIO100` are different memory, and guessing returns a plausible reading from the
  wrong area.
- **Session reads for every collectable protocol** — one connection held for the whole
  run instead of one per sample (see the fix below).
- **`demo/oee-line` — ninety seconds, no hardware.** The four commands a site runs, in
  order, against a real pymodbus server, with the device process killed part-way
  through. The outage is the demo: the line was producing throughout, the tool simply
  could not see it, and the measurement must not call that downtime.
- **`iaiops scan` — site discovery from the command line.** The engine landed in
  #161 but had no entry point, so a survey could only be run by writing Python.
  Six commands: `profiles` / `plan` / `run` / `list` / `report` / `prune`.
  `scan plan` emits **nothing** and prints the full preview — every host, every
  port, every packet class, the worst-case duration, and the explicit list of
  what the tool never does — which is the artifact a controls engineer signs
  before anyone touches the network. `scan run` shows that same preview and asks
  once before sending (`--yes` skips). Verified against a real pymodbus device in
  a container: `iaiops scan run` → SQLite → HTML with the vendor intact.

- **`iaiops case open` — the entrance the learning loop never had.** `case list`
  printed "cases are opened from detected stoppages" while `open_case` had no
  caller anywhere outside its own module, so an empty list read as "you have had
  no stoppages" rather than "nothing here ever creates a case". It opens one case
  per long stoppage found in the collected history, each carrying what someone
  DID afterwards straight from the audit trail — zero extra typing, because those
  actions were already recorded. Re-running is safe: an answered case is returned
  untouched rather than replaced with a blank.
- **`iaiops diag learn-weights --site` — and the exit it never had either.**
  `to_corpus` also had no caller outside tests, so the corpus a site spends years
  accumulating could not reach the learner that exists to consume it; the only
  input was a hand-written JSON file. `--independent-only` trains on labels this
  tool did not suggest, so a site can see whether its weights survive without the
  ones its own ranking shaped.
- `measure_availability` now returns `stop_windows` — each stoppage's onset and
  duration, longest first — so a stoppage is addressable rather than only
  countable.

- **The Six Big Losses, from measured inputs.** `six_big_losses` had existed since
  the OEE brain was written and was reachable from nowhere — a sweep for public
  core functions with no production caller found it referenced only by its own
  docstring and `__all__`. Four of its five inputs are now derived by `collect` +
  `oee measure`, and `iaiops oee measure` reports the decomposition. Without a
  declared good-count tag or ideal cycle it refuses and names the tag to declare:
  the shortcut (`good_count = total_count`) reports a perfect Quality factor that
  reads exactly like a line with no rejects. "Planned time" here is stated as
  OBSERVED known time, not the plant's schedule, which nobody has given us.

- **A verdict now says how much history stands behind its ranking**, not only how
  confident it is (D24). `reliability` reports whether the shipped defaults or a
  site profile is in use and, when known, how many confirmed incidents shaped it
  — "90% from a site with three recorded cases is not 90% from a site with three
  hundred", and a verdict that reports only the first invites the reader to
  supply the second from imagination.

- **`iaiops oee measure --report x.html` — the number you can hand to someone.**
  `scan` and `compliance` could both write a file; the figure this product most
  wants a customer to see was the only one that could not be put on paper, and a
  terminal is the wrong medium for a five-minute conversation with a plant
  manager. One self-contained file: no fonts, scripts, styles or images from
  anywhere and no network request when opened, so it works on an air-gapped
  laptop and survives being forwarded as an attachment. `--lang en|zh`.

  **Coverage comes before the number, and cannot be moved.** The scan report
  argues that its section order IS its argument — it opens with what it did, not
  what it found. Here the equivalent is that "we could see 85% of the window"
  precedes "OEE 66%": a report that leads with the figure and footnotes the
  coverage hands the reader a measured fact and lets them supply a false
  precision. The page also carries the **prerequisite row a sales deck leaves
  out** — what had to be declared to produce each figure, and what is still
  missing — because a demo that hides it fails on first contact with a real site.

  The demo now writes `oee-demo.html`, with its own honesty caveat rendered onto
  the page (in the report's language): a forwarded report of a shift compressed
  into seventy seconds, without that sentence, reads as a real plant's real OEE.

- Shared report primitives moved to `iaiops/core/report/` (escaping, CSS, the
  document skeleton, and the repo's first inline-SVG charts). The repo had two
  report builders sharing **no code**, with two escape helpers and two `_cell`
  functions whose contracts disagreed; a third copy would have been the point of
  no return. `discovery/report.py` now imports them back and its output is
  **byte-identical** across the change.

- **A verdict that is also an investigation plan, and a grade nothing can fake**
  (HLD §10.3④, D28-D30). Every hypothesis now carries its **counter-evidence**,
  its **gaps** — what is missing to raise the grade — and **one next step**. In a
  plant the gap is usually a field action (somebody with an instrument), not
  another pass over registers already collected, so the gap table names the
  action per cause.
- **Four conclusion grades: `candidate` / `probable` / `confirmed` / `excluded`.**
  "Ruled out, and here is why" and "scored low" are statements of different
  strength, and only the first makes a plant stop spending time on that branch.
- **Exclusion by time order.** `_proximity_scale` already knew a signal came after
  the onset and dropped it to a quarter weight — then discarded the reason. A
  cause supported *only* by post-onset signals is now `excluded`, saying how many
  seconds after and that a cause cannot follow its effect, and it can never be the
  primary cause however it scored. The exclusion names what would overturn it:
  clock skew between the device and the collector.
- **`confirmed` is reachable only from outside the ranking** (D29). A confidence
  computed from the same evidence that produced the ranking only means the ranking
  agrees with itself. `iaiops diag rca --from-case <id>` reads a cause a person
  already recorded through `iaiops case confirm`, closing a loop whose two halves
  could not see each other; `--confirmed-basis measurement|reproduction|human`
  covers the other two routes, and a malformed confirmation is refused rather than
  ignored.

- **`uns_publish` — telemetry into an MQTT broker / Unified Namespace.** A new
  user-facing MCP tool and a new `iaiops[uns]` extra. Listed here late: it shipped
  in #163 and this section carried no entry for it until a pre-release audit found
  the gap. That matters more than a missing line usually would — it is an
  **egress** path, withheld by `IAIOPS_NO_EGRESS=1` along with the other five, and
  somebody diffing release notes to decide whether to re-review their air-gap
  posture would not have learned it existed.

### Fixed
- **`diag learn-weights` output could not be fed to `diag rca --weights`**, which
  is exactly what that option's help text tells you to do. The learner returns
  `{cause_weights, n_incidents, per_cause, rationale}` and the consumer expected
  the inner map alone, so the documented composition failed with
  `cause_weights['cause_weights'] is not a known cause` and a user had to
  hand-extract it. A whole profile is now accepted (a bare map still is), and
  unwrapping it is what recovers the case count reliability reports.
- **Parts made while the collector was blind inflated Performance.**
  `count_production` summed every positive delta while `measure_availability`
  excluded blind seconds from run time, so the numerator described a longer
  window than the denominator and Performance rose in proportion to how blind the
  run was. Measured across a 25s blind window: **1.251 → 0.995**, a quarter of a
  factor, all upward — a higher Performance is a higher OEE. Past 100% the tool
  then blamed its own inputs, telling the operator their cycle time or counter
  must be wrong when neither was. Increments spanning a gap are now skipped by the
  same rule the availability path uses, and reported rather than absorbed.
- **The demo declared an ideal cycle ten times too slow**, so the artefact meant
  for a customer conversation printed "Performance computed to 1681.2%" and a
  warning about its own input. It also declared no good-count tag, so Quality —
  the factor a buyer asks about first — was never shown. The simulated line now
  scraps about one part in 25, and the demo reports a complete OEE plus the Six
  Big Losses.
- **An IoTDB historian could not serve a Modbus line at all.** A bare number is
  not a legal IoTDB path node, and a Modbus site's tags ARE numbers — `collect
  run` stores samples under the register address, so a plain line yields the tags
  `0` and `10`. Unquoted, a live server refuses both directions:
  `ILLEGAL_PATH(509)` on insert and "no viable alternative at input" on select.
  Every fixture in the live suite used alphabetic metric names, which happen to
  be legal unquoted. Path nodes are now always backquoted — verified on the same
  live server that a quoted node and its bare form are the same node, so series
  written by earlier versions still read.
- **A running line measured as 0% available.** YAML spells a status word
  `running_when: "2"` and a Modbus register arrives as the float `2.0`;
  `is_running` compared those as text, `"2" != "2.0"`, and a line that ran for
  88% of its samples reported `0.00% over 97.54% coverage`. Measured against a
  real device — the same data now reads **88.56%**. Note the direction: zero
  availability turns a healthy line into unexplained downtime, which is exactly
  the loss a vendor then offers to fix. Two guards now: the same number matches
  however it is spelled, and a run-state tag that was sampled and NEVER matched
  refuses to report a figure at all, printing the declared value beside the ones
  actually observed.
- **One command read two config files.** `IAIOPS_CONFIG` was honoured by
  `load_config_env()` — which the shared brain modules call — and ignored by
  `load_config()`, which the CLI and everything else call. So a single
  `iaiops diag rca-live` took its ENDPOINTS from `~/.iaiops/config.yaml` and its
  HISTORIAN from `$IAIOPS_CONFIG`. The visible failure is the mild one ("endpoint
  not found"); the one that matters is quiet — point the override at a plant
  while a stale file sits in the home directory and the copilot pairs live
  evidence sampled from one machine with history pulled from another, with no
  error anywhere. The override is now resolved in one place every caller goes
  through.
- **Timestamps were truncated to whole seconds.** At a 200ms sample rate every five
  samples shared one stamp, so the observed cadence computed as 0.000s, ordinary
  sampling intervals were reported as lost connections, and the plan advertised
  resolving stoppages down to 0.4s while the stored data could not distinguish
  anything under two seconds. Found by pointing the collector at a real device.
- **Collection opened one TCP connection per sample.** Measured at 500ms over two
  tags: 3.7 connections a second and ~110 sockets left in `TIME_WAIT` — 1.8 million
  connections across the week-long run this feature exists for. One session per run
  now: `TIME_WAIT` 110 → 0. Every test passed either way, and a Python Modbus server
  tolerates what a PLC may not.
- **A configured TDengine historian was unusable without a vendor tarball.**
  `HistorianConfig` could not express the wire, so every reader took the default —
  `native`, which needs `libtaos`, a vendor download that is not on PyPI. A site that
  configured TDengine got "the native TDengine client could not be loaded" for every
  incident, with nothing in the config able to say "use REST". `transport:` is now a
  config field, validated at load.
- **The OPC-UA CI harnesses published ports the kernel hands out as ephemeral.**
  Linux uses 32768-60999 for ephemeral source ports, so an outbound connection
  made anywhere in the job — a docker pull, a `uv` download, a TSDB client —
  could be holding 50000 or 50010 when docker tried to publish it, failing the
  whole lane with `address already in use`. It surfaced on a docs-only PR, which
  is the signature: it depends on which port the kernel happened to hand out, not
  on the change. Both servers moved below the range, and the harness now reads
  the range from the kernel and refuses an ephemeral port rather than binding it
  and failing at random.
- **The BACnet CI harness picked an address that does not exist.** It derived its
  second address by incrementing the last octet, so a runner ending in `.255` —
  perfectly ordinary on a /20 — produced `10.1.0.256`. Intermittent by nature, which
  is why main stayed green for weeks with it in place.
- **`ScanNotFound` reached the user as a traceback.** `cli_errors` translated
  `KeyError` but not its parent `LookupError`, so a carefully written teaching
  message ("nothing has been stored yet, run `scan run` first") was swallowed and
  replaced by a stack trace. The caught families now include `LookupError`.
- **`scan plan --out preview.json` wrote plain text.** The output file's format
  followed the `--json` flag rather than its own suffix, producing a `.json` file
  whose extension lied about its contents. Format now follows the suffix;
  `--json` governs stdout only.
- **Asking for a report of a scan id that does not exist** printed the store's
  path rather than saying nothing had been stored. "That id is not here" and
  "nothing has ever been stored" are different problems and someone typing an id
  from memory on a fresh machine needs the second answer.
- **A configured IoTDB historian was documented with a database name IoTDB
  cannot accept.** `HistorianConfig`'s own docstring said `database: iaiops`;
  every IoTDB path starts at `root.`, so following our documentation produced a
  server-side SQL parse error naming *our* generated statement. The config now
  refuses a non-rooted path and names the fix (`root.iaiops`) while the operator
  is still looking at the file they typed — and so does the sink, so the rule
  cannot be true on the read side and false on the write side.
- **Every historian failure escaped as a traceback.** The TSDB client libraries
  raise their own exception types (taospy's `ProgrammingError`, IoTDB's thrift
  `StatementExecutionException`), which are neither `ValueError` nor `OSError`,
  so nothing in the CLI's error harness recognised them: an unreachable server
  or a dropped database produced 111 lines of stack trace with our SQL in it.
  Both readers now translate client failures into one `SinkError` teaching line,
  and `cli_errors` catches that family. Found by pointing a `config.yaml` at a
  live Apache IoTDB and running `iaiops historian coverage` — every existing test
  either mocks the reader or constructs it directly with keyword arguments, so
  the path a customer takes had never run.


## 0.22.0 — 2026-08-02

> **A minor version because the floor moved: `asyncua>=2.0`.** On 1.x a session against
> an OPC Foundation .NET-stack server was impossible, so OPC-UA could only ever be
> tested against `asyncua` on both ends. With that wall gone, the last register items
> fell — a third-party OPC-UA stack, certificate trust enforced both ways, TDengine
> without its vendor library, EtherNet/IP program scope, and a second MCP implementation
> in another language. **Each one found something**, including a defect in every
> published container image and an RCA window that kept the wrong half of its samples.

### Fixed
- **`eip_list_tags` never returned program-scoped tags**, though its own note promised
  they "appear as `Program:<prog>.<tag>`". It called `get_tag_list()`, which is
  controller scope only; a program's tags are a *second* request carrying an
  extended-symbol segment. Now `get_tag_list(program="*")` on the Logix route (Micro800
  has no program scope and keeps the plain call).
- **The MCP handshake reported the SDK's version as the server's.** FastMCP takes no
  `version` and the low-level server defaults to `None`, so a client asking "which
  iaiops am I talking to?" was told the `mcp` package's version. Found by driving the
  server from the TypeScript SDK, whose client surfaces `serverInfo`.
- **The published container images could not write their own audit chain.**
  `deploy/margo/Dockerfile` declared `VOLUME` *after* `USER`, so Docker created
  `/home/iaiops/.iaiops` as root:root 0755 while the app runs as uid 10001 — in every
  image up to 0.21.1, `IAIOPS_HOME` was unwritable. The governance layer behaved exactly
  as designed (reads proceeded with a warning, **every high-risk write was denied
  fail-closed** with an actionable message), but the images were unusable for writes and
  kept no audit trail for reads. The directory is now created, owned and 0700-ed before
  the volume is declared. Found by running the published image under the constraints an
  immutable edge host imposes.
- **A truncated pre-incident window kept the wrong end.** Every reader returns rows
  oldest→newest and cuts at `LIMIT`, so a window holding more samples than the cap lost
  its most recent ones — for an incident investigation, the minutes closest to onset.
  `SampleFilter.newest_first` now selects which end survives, pushed into the SQL of
  all three readers (SQLite, TDengine, IoTDB) rather than faked by reversing in Python,
  and `gather_pre_incident` sets it. Rows still come back oldest→newest and the default
  is unchanged, so nothing else moves.

### Changed
- **`asyncua` 2.x is now required** (`asyncua>=2.0,<3`). On 1.x a session against an
  OPC Foundation .NET-stack server was impossible — it sent a `ServerUri` that OPC UA
  Part 4 §5.6.2 says must be empty unless the endpoint has a `gatewayServerUri`, and
  that stack enforces the rule. 2.x makes the field opt-in. The migration was the pin
  and the version strings the skills quote: **all 64 existing OPC-UA tests passed
  unchanged.** The `client_interop` verdict stays, with remediation rewritten for a
  world where the pin already excludes 1.x.

### Testing
- **A SECOND MCP implementation** (`tests/test_mcp_second_impl_live.py` +
  `tests/mcp_ts_client/`). Every MCP test so far ran the Python SDK's client against a
  server built on that same SDK — 2a for our code, but a misreading *inside* the SDK
  would satisfy both ends. The TypeScript SDK is another language and another codebase;
  the annotations promise is now asserted through its parser, and it is what caught the
  version above.
- **EtherNet/IP breadth**: program-scoped tags listed, read and written; PCCC **ST**
  string files with their byte-swapped words. Both found harness defects that only a
  two-letter file type or a second scope could expose — element sizing keyed on
  `key[0]` turned `ST` into `S`, and File 0's POSITIONAL numbering reported `ST18` as
  `ST9` when the unused rows were left empty.
- **`immutable-host` CI job + `scripts/immutable_host_check.sh`** — Margo's device role
  is a hardened, centrally-managed host; validating on a specific one needs that vendor,
  but what an immutable host demands *of an application* does not. Every build now
  proves the image runs non-root under a read-only root filesystem with all mutable
  state in the declared volume, and that the audit chain accepts a row under those
  constraints. The check fails against the images published before this change, which is
  how the defect above was found.
- **The Margo application package is named the way Margo's own reference sandbox
  requires** (`iaiops-compose-app-package-<version>`). `margo/sandbox` — which did not
  exist when this integration was written — rejects anything without the
  `<name>-<type>-app-package` suffix on upload. The old `iaiops-margo-package-<version>`
  name still ships as a signed alias for existing consumers.
- **OPC-UA reaches a real 2a.** `test_opcua_thirdparty_live.py` no longer asserts that
  sessions are impossible; it drives Microsoft's opc-plc — an independent
  implementation — through a session, a browse of the SERVER's own address space,
  typed reads carrying its status codes and timestamps, and its own `BadNodeIdUnknown`.
- **Certificate trust is enforced, not merely offered**
  (`test_opcua_cert_trust_live.py` + `scripts/opcua_cert_harness.sh`). Against a strict
  opc-plc: an unknown client certificate is refused and filed under `pki/rejected`,
  promoting it opens the encrypted Basic256Sha256 session, and — the finding no
  in-process test could produce — **a trusted certificate whose SAN URI does not match
  the client's ApplicationUri stays refused**. `asyncua`'s own server runs a permissive
  validator, so the connector's whole `certificate` verdict class had never been
  produced by something that enforces it.

## 0.21.1 — 2026-08-02

> **Four independent reviews of 0.21.0, and three more product defects.** The
> sweep that produced 0.21.0 was reviewed by one pair of eyes — its author's. Four
> reviewers over the same diff found what that missed, including a wrong answer in
> the RCA path that predates all of this work and had never been noticed.

### Fixed
- **The RCA pre-incident window kept each tag's OLDEST samples and reported them as
  complete.** `gather_pre_incident` pulls the window with ONE bounded query across
  every tag; every reader returns rows oldest-first. On a historian holding more tags
  than `MAX_WINDOW_ROWS / MAX_SAMPLES_PER_TAG`, the cap lands long before the window
  ends and each tag keeps only its earliest handful — measured at 3 samples per tag
  out of 30 for a 40-tag store, on IoTDB **and** on the local SQLite store, so this
  was never one dialect's quirk. For a *pre-incident* window that discards precisely
  the minutes before onset, and `sample_count` counted the diluted rows as though the
  window were whole. The selected tags are now re-queried individually when the first
  read was truncated — at most `MAX_HISTORY_TAGS` bounded reads, and none at all when
  the window fit.
- **An IoTDB result whose columns are named something else returned "no data"
  instead of an error.** 0.21.0 made the header/field *arity* loud but left the
  *names* silently defaulted, so a header with the right shape and different labels
  (a qualified `COUNT(root.db.t1.value)`, a `__device`) passed the check while every
  lookup missed — `historian_query` returning `[]`, `historian_coverage` reporting
  every tag as `rows: 0`. Both column sets are now required by name.
- **A malformed `endpoint_url` still leaked a thread.** 0.21.0 guarded everything
  *after* asyncua's constructor, but the constructor starts the ThreadLoop and only
  then parses the URL — so `opc.tcp://[::1:4840` (an unclosed IPv6 bracket) raised
  with the loop already running and no client for anyone to disconnect. The URL is
  now parsed before the client is built, which is also where the error belongs.

### Testing
- **CI gates on the port the tests actually connect to.** The readiness probes added
  in 0.21.0 checked container banners and in-container commands; every live test
  gates on a TCP connect from the runner. A container that printed its banner and
  died, or whose port never published, would have passed the gate and let the tests
  skip on a green build — the exact hole the gate was added to close.
- **A skipped live test now fails the build where the scaffolding was promised.**
  `pytest -q -rs` prints "6 skipped" and exits 0, so a dropped `export`, a renamed
  env var or a client library that stops importing silently converted a dedicated CI
  step into a no-op. `IAIOPS_REQUIRE_LIVE=1` (set by the PROFINET, BACnet and
  integration steps) turns any skip into a failed run, with one explicit escape
  hatch — `@pytest.mark.optional_live` — for scaffolding the workflow itself declares
  non-fatal, today only the vendor-CDN libtaos client.
- **`opc-plc` and `nats` images are pinned**, like everything else in that lane; note
  ⁸'s interop claim was anchored to whatever `latest` happened to be that day.
- Test fixes: the PROFINET unicast-Get test could pass on the IdentifyAll fallback it
  exists to exclude; the MCP allowlist had no positive case, so a middleware that
  403'd everyone would have passed; a tool-failure assertion accepted invented
  register data; TDengine's `until` bound had never reached a real taosd; a class-level
  fake dataset leaked between tests.
- Harness fixes: the PCCC File-0 read answered out-of-range with success and no data,
  which spins pycomm3's directory loop forever with no timeout; masked writes to 4-
  and 6-byte elements were refused as bad addresses; the DCP station swallowed
  exceptions into silence (they are recorded and asserted now) and half-applied a
  short Set; `harness_process` piped a child's stderr nowhere and could deadlock it at
  64 KiB; the veth script armed its cleanup trap too late and reused half-built
  interfaces.

### Documentation
- Both MCP rows in `docs/VERIFICATION-RECORD.md` carry note ⁹: client and server come
  from the same SDK, which is the caveat SECS/GEM's note ⁴ already made for the same
  situation. A blank line was also breaking that table's rendering.

## 0.21.0 — 2026-08-02

> **A verification sweep, and what it cost.** Every remaining item on
> `docs/VERIFICATION-RECORD.md`'s follow-up register was cleared by pointing code at a
> real counterparty for the first time: two historian databases, a PROFINET wire, two
> EtherNet/IP driver routes, the MCP network transports, and an OPC-UA server from a
> stack nobody here wrote. **Five product defects came out of it** — including a reader
> that returned one machine's values under another machine's tag name, and a query that
> could never have run against any real server. Every one of them had passing unit
> tests, because the mocks had been written to match the code rather than the server.

### Fixed
- **The IoTDB reader returned one tag's values under another tag's name.** A wildcard
  `SELECT value FROM root.db.*` declares one column per series, and the reader zipped
  that header against each record's fields. A real IoTDB 1.3.2 returns the fields
  **compacted** when a `WHERE` clause is present — so a time-bounded query, which is
  precisely what the RCA copilot asks for, came back with the right numbers under the
  wrong labels. On a plant floor that is a wrong answer wearing the right shape. The
  reader now uses `ALIGN BY DEVICE`, whose rows carry their own device label, and a
  header/field arity mismatch raises instead of truncating silently.
- **`historian_coverage` against TDengine raised for every caller.** The query used
  `MIN(ts)` / `MAX(ts)`, and taosd 3.x rejects both on a TIMESTAMP column
  (`[0x2802]: Invalid parameter data type : min`). Now `FIRST(ts)` / `LAST(ts)`, the
  timestamp-ordered equivalents the dialect actually provides.
- **`opcua_diagnose_connection` leaked a thread on every failed diagnosis — and hung
  the process.** `asyncua.sync.Client` starts a **non-daemon** thread loop in its
  constructor. Two paths abandoned a client without stopping it: the failed-connect
  branch returned its verdict without disconnecting, and `_build_opcua_client` left an
  already-constructed client behind if anything after the constructor raised (a locked
  secret store behind `password()`, an unparseable security string). The tool exists to
  be called when connections are failing, so the leak sat on exactly the path that
  matters: `iaiops doctor` (which classifies every unreachable OPC-UA endpoint) never
  returned to the prompt, and an MCP server accumulated one thread per failed
  diagnosis. Both now release the client.
- **A `BadServerUriInvalid` connect failure was classified `unknown`** ("inspect the
  detail"), for a failure that is precise and entirely client-side. New verdict class
  **`client_interop`**, naming the cause and absolving the site: `asyncua` 1.x sends a
  `ServerUri` that OPC UA Part 4 §5.6.2 says must be empty unless the endpoint has a
  `gatewayServerUri`, and OPC Foundation .NET-stack servers enforce it — so **sessions
  against that stack cannot open at all** until this package moves to `asyncua` 2.x.
- **`profinet_discover` / `profinet_asset_inventory` documented fields that are always
  empty.** `pnio_dcp.Device` (1.2.0) exposes name_of_station / MAC / IP / netmask /
  gateway / family and nothing else, so `vendor_id`, `device_id` and `device_roles`
  never populate — the station returns DeviceID and DeviceRole blocks and the client
  drops them, which makes `io_controller_count` structurally 0. The connector and MCP
  tool docs said otherwise; they now name the limit, and the live test asserts it so a
  pnio-dcp that fixes it turns red.

### Testing
- **`tests/test_tsdb_live.py`** — IoTDB and TDengine round-trips against real servers
  (rung 1 → **2a**): sink write → reader read-back, server-side time and tag filters,
  the `LAST` and aggregate result shapes, the `value` reserved-word DDL.
- **`tests/test_profinet_live.py` + `tests/profinet_dcp_station.py` +
  `scripts/profinet_dcp_harness.sh`** — real `pnio-dcp` over a **veth pair** (mock only
  → **2b**). PROFINET had been written off as hardware-gated alongside EtherCAT; that
  was wrong, because DCP is request-response over layer-2 Ethernet, so the missing half
  is a *responder*, not a device. Covered: IdentifyAll with the MAC read off the reply's
  Ethernet header, identify-by-name hit and miss, a unicast DCP Get proven by what the
  station *received*, and the governed DCP Set applied, verified against the station's
  own state and reversed through the captured BEFORE — with the dry run proven to put
  no Set on the wire.
- **`tests/test_eip_pccc_live.py` + `tests/eip_pccc_plc.py`** — EtherNet/IP's other two
  driver routes reach **2b**, next to the Logix one. `slc` needed a second protocol in
  the harness rather than a second tag: CIP service 0x4B carrying DF1/PCCC, numbered
  data files, and `SLCDriver` parsing replies at fixed byte offsets. Covered: the
  processor-type diagnostic, the whole File-0 directory sequence behind
  `eip_list_tags`, typed reads (signed N, float F, bit B, timer accumulator), a masked
  bit write that leaves its neighbour bit alone, and BEFORE-capture round-tripped as an
  undo. `micro800` needed the harness to *identify* as one — pycomm3 switches on the
  catalog number in ListIdentity, not on anything the connector passes — asserted by
  the Multiple Service Packet that does **not** reach the wire, against a live Logix
  control that does. This also closes the connector's standing gap: PCCC has no symbol
  table for pycomm3 to validate against, so a bad address really does reach the
  controller and really is refused.
- **`tests/test_mcp_http_live.py`** — the MCP server's **network transports** reach
  **2a**, next to stdio. The SDK's `streamablehttp_client` and `sse_client` drive the
  real entrypoint running under uvicorn: initialize, `list_tools()`, and a tool call
  whose connector failure comes back as content rather than killing the session. It
  also covers **the IP-allowlist middleware, which exists on no other transport** — a
  client outside `IAIOPS_ALLOWLIST_IPS` gets a 403 before any MCP conversation starts,
  with an unconfigured server proving the control is off by default. These transports
  are what `deploy/margo` and the IGEL submission expose, and nothing had ever made a
  request to one.
- **`tests/test_opcua_thirdparty_live.py`** — OPC-UA meets a stack nobody here wrote:
  Microsoft's opc-plc, on the OPC Foundation .NET stack. Transport, secure channel and
  endpoint discovery interoperate; sessions do not, for the ServerUri reason above.
  Every other OPC-UA test has `asyncua` on both ends, so none of this was visible. The
  test is written to go **red** the day sessions start working.
- **MTConnect `/assets`** is now part of the live-agent round-trip: a third document
  type with its own namespace, where the asset *type* is the child element's name and
  the nested cutting-tool life-cycle elements must not be counted as assets.
- **CI runs all of it.** The gate job starts a NATS broker (the egress live tests had
  been skipping on every run) and the PROFINET veth harness under `sudo`; the
  integration lane starts IoTDB, taosd and opc-plc. Two container gotchas are recorded
  in the workflow: `libtaos` needs a writable `/var/log/taos` or `taos_connect` reports
  a bare "Permission denied", and a taosd container must advertise
  `TAOS_FQDN=localhost` or the client reconnects to a name only it can resolve.
- The mocked reader tests now reproduce the **shapes the servers returned** rather than
  the shapes the parser expected, and both TSDB sinks' docstrings drop a "verified
  2026-06-30" claim that no longer had anything behind it.

## 0.20.4 — 2026-08-02

> **Two things that reported success without evidence.** NATS egress took two minutes
> to fail against an unreachable broker while `timeout_s` sat there looking
> authoritative, and `bacnet_write_property` claimed `applied: true` on the strength of
> "the client did not raise" — which, for BAC0, is true whether the controller honoured
> the write or silently dropped it. Both were found by pointing the tests at real
> counterparties for the first time, along with the product's own primary interface:
> nothing had ever driven the MCP server with a real MCP client.

### Fixed
- **NATS egress took 120 seconds to fail against an unreachable broker**, despite
  `timeout_s`. `connect_timeout` does not bound the attempt — nats-py works through its
  server pool on its own cadence, and neither `allow_reconnect=False` nor
  `max_reconnect_attempts=0` changed it (measured, not assumed). `stream_publish` is an
  MCP tool, so that was a **two-minute hang on a typo'd address or a sealed site**, and
  `@governed_tool`'s `timeout_seconds` is advisory — it warns, it does not cancel. A hard
  `asyncio.wait_for` now bounds the whole connect-publish-drain at `max(2 x timeout_s, 5s)`
  and raises a teaching error. **120s → 5s.** Found by timing a test, not by reading code.
- **`bacnet_write_property` reported `applied: true` without any evidence.** BAC0's
  `write()` returns `None` and raises nothing **whether the device honoured the request or
  silently dropped it** — verified against a live bacpypes3 device, where the present-value
  never moved and nothing in the result said so. On a write that moves a building setpoint,
  "it did not raise" is the wrong basis for claiming success.

  The write now reads the value back and reports it (`after`, `verified`), and
  deliberately does **not** judge a mismatch as failure: on a commandable object a higher
  priority legitimately holds the value, and only the operator knows the priority scheme.
  When `after` differs it carries a `verify_note` naming the two usual causes. Reporting
  is the honest primitive here; asserting was not.
- **`test_deliver_without_nats_raises_teaching_error` was environment-dependent and
  misnamed.** `nats-py` *is* installed, so the ImportError branch it claimed to cover can
  never run; what it exercised was a failed connection to `localhost:4222`, and only while
  nothing happened to be listening. Running a local broker turned it red — as it would on
  any developer machine with NATS running. Renamed and aimed at a closed port.

### Added
- **The MCP server is now driven by a real MCP client over stdio**
  (`tests/test_mcp_stdio_live.py`). Every other test calls tool functions in-process,
  leaving the product's **primary interface** unexercised. Seven tests launch the real
  `mcp_server.server:main` entrypoint as a subprocess and drive it with the SDK's own
  `stdio_client` + `ClientSession` — rung **2a**. Two of them carry product promises that
  were previously only checked against our own registry, which is not where a client looks:

  - **the `ToolAnnotations` a client actually receives.** 0.20.1's point is that a client
    can tell a plant write from a browse programmatically; now verified where it is
    consumed. Every tool must arrive annotated, and `mqtt_publish` must arrive
    `destructiveHint=True`;
  - **what `IAIOPS_NO_EGRESS=1` withholds, as seen from outside.** The airgap promise is
    about what a *client* can see; asserting it against our own registry assumed the thing
    under test. Now the client is asked, and the reads must survive the gate.

  Also: the JSON-RPC round trip, a connector failure arriving as readable content rather
  than a session-killing protocol error, and `IAIOPS_MCP` profile selection through the
  real entrypoint. Mutation-verified — disabling the annotation derivation fails two
  tests, neutering the egress gate fails one.
- **Egress sinks against real servers** (`tests/test_egress_live.py`). `test_egress_nats.py`
  monkeypatched `_deliver` and `test_influxdb_sink.py` replaced the whole `requests` module,
  so the two things that actually leave the building — the NATS wire format and the InfluxDB
  line protocol — were only ever checked against our own idea of them. Now a **real NATS
  broker** (published messages are read back off it by a real subscriber, because "did not
  raise" would prove nothing) and a **real HTTP endpoint** recording exactly what the
  InfluxDB sink puts on the wire: measurement, value, bucket/org query, `Authorization`
  header, and that five points become **one** request rather than five.
- **The BACnet write path is live** (`tests/test_bacnet_live.py`) — dry-run verified by
  reading back rather than by trusting the returned dict, and the BEFORE capture checked
  against what the device actually held.

### Added
- **EtherNet/IP now runs over a real CIP session** (`tests/test_eip_live.py` +
  `tests/eip_plc_harness.py`) — the largest of these gaps, because
  `LogixDriver.open()` performs a five-step dance before a single tag is read:
  RegisterSession, ListIdentity, Forward Open, controller info, and a full **tag-list
  enumeration** off the Symbol object. `test_eip.py` monkeypatches the driver, so none
  of it ran. Nine tests now cover the session, the tag-list upload, single and
  Multiple-Service-Packet reads, and `eip_write_tag`'s **BEFORE capture verified by
  reading the tag back**.

  Same evidence caveat, recorded in the module docstring: `pycomm3` ships no server, so
  the far end is ours. **A physical ControlLogix stays 待核实.**

  Three requirements the real driver imposed that a mock cannot, each found by it
  rejecting the previous answer: a CPF reply missing its **item-count** field shifted
  everything two bytes and surfaced as `Error packing -128 as USINT` (the service byte
  read from the wrong offset); refusing **Forward Open** is not a shortcut, since the
  driver retries with a standard Forward Open and then fails, so connected messaging
  had to be served too; and a multi-tag read is not N reads but one **Multiple Service
  Packet** with N embedded requests.

  Mutation-verified: ignoring the symbolic tag name (4 failures), dropping the CPF item
  count (8), and dropping the connector's BEFORE capture (1).
- **S7comm now runs over a real ISO-TSAP socket** (`tests/test_s7_live.py` +
  `tests/s7_plc_harness.py`). `test_s7.py` monkeypatches `_build_s7_client`, so `pyS7`
  never ran — the COTP connection request, the PDU-size negotiation, the S7ANY address
  encoding (S7 addresses go on the wire in **bits**, `start * 8 + bit_offset`) and the
  per-item response parsing with its return codes and fill bytes were all assumed.
  Eleven tests now drive the genuine client, including `s7_write_db`'s **BEFORE capture
  verified by reading the data block back**.

  Same evidence caveat as MC and recorded in the module docstring: `pyS7` ships no
  server, so the far end is ours. **A physical S7 CPU stays 待核实.**

  Three things this asymmetry caught that a mock could not:

  - the harness first read a *request's* parameter at the **response** offset (19 vs 17
    — an ACK_DATA header carries an error class/code that a job header does not), then
    mis-indexed the 12-byte item spec by one. Both surfaced as pyS7 rejecting the answer;
  - mutation testing showed `test_bit_addresses_select_the_right_bit` does **not** prove
    what its first docstring claimed. pyS7 **coalesces** neighbouring bit tags into one
    byte read and extracts the bits client-side, so the harness's single-bit branch is
    dead on that path — deleting it fails nothing. The test still discriminates the
    failure that matters (returning the byte whole would make bit 1 read `True`), but it
    pins the connector's *address* construction plus pyS7's extraction, not our bit
    handling. Both the test and the harness now say so rather than looking covered.
- **Mitsubishi MC now runs over a real socket** (`tests/test_mc_live.py` +
  `tests/mc_plc_harness.py`). `test_mc.py` monkeypatches `_build_mc_client`, so
  `pymcprotocol` never ran: 3E frame assembly, device encoding, signed-word decode and
  bit unpacking were all assumed. Nine tests now drive the genuine `Type3E` client over
  TCP, including `mc_write_words`'s **BEFORE capture verified against the device** — the
  value the connector reports as `before` is read back from the PLC, because that is what
  an operator would replay to roll back.

  **Evidence level, stated in the module docstring rather than left to inference.**
  `pymcprotocol` ships no server, so the far end is written by us from the frame spec,
  unlike the protocols that face a real third-party counterparty (pymodbus, bacpypes3,
  opendnp3, mosquitto, …). If we misread the 3E spec, harness and expectations are wrong
  together. It is still far more than a mock — the real client parses every byte, so a
  wrong subheader / length / status offset fails against the library rather than against a
  stub that agrees with us, and the harness *decodes* the request, so D100 / M0 / a wrong
  offset return different data. **Weaker than a third-party round-trip; a physical MELSEC
  CPU stays 待核实.**

  Mutation-verified: flipping the harness's bit-nibble order, reading one register too
  many in the BEFORE capture, and dropping the BEFORE capture each turn it red.

### Fixed
- **SECS/GEM presented raw protocol bytes as data when a tool did not implement a
  function.** Found by giving SECS/GEM a real equipment to talk to (below).
  `GemEquipmentHandler` does not implement **S7F19** — process-program transfer is an
  *optional* GEM capability that many real fab tools omit — and secsgem answers such a
  request by handing back the **undecoded message bytes**. Those flowed into `_plain`,
  which hex-encodes bytes, and the connector labelled the result `process_programs`:

  ```json
  {"count": null, "process_programs": "0000871300009e036f8a"}
  ```

  That blob is the echoed S7F19 request header (session `0000`, stream 7, function 19).
  Not a fabricated *value*, but non-data under a data label, with `count: null` as the
  only hint — an operator, or a model reading the tool result, would reasonably report
  that the equipment has process programs.

  All six read paths (`S1F11`, `S1F3`, `S2F29`, `S2F13`, `S5F5`, `S7F19`) now detect a
  raw-bytes reply and return a teaching error naming the stream/function and the likely
  cause. Any of them can hit this: an unsupported function is normal on real equipment,
  and only S7F19 happened to be the one secsgem's own equipment lacks.

### Changed
- **The libtaos install step no longer makes every build depend on a vendor CDN.** The
  version added a day earlier worked once, then a later run spent 300s hanging on
  `www.taosdata.com` and failed the build — a reliability regression introduced with that
  step. It is now cached (the usual path never touches the network), bounded
  (`--connect-timeout 20 --max-time 240 --retry 2`), and non-fatal: on a definitive
  failure it emits a loud `::warning::` and the binding test skips with its own honest
  reason. An **announced** degradation, not a silent one — making the whole build depend
  on a third-party CDN being reachable is the wrong trade for one symbol check.

### Added
- **SECS/GEM now has a real equipment** (`tests/test_secsgem_live.py` +
  `tests/secsgem_equipment_harness.py`). `test_secsgem.py` monkeypatches the host
  handler, so the HSMS connect/select handshake, the SECS-II encoding of each request
  and the decoding of each reply were all assumed. A real `GemEquipmentHandler` now
  listens in HSMS **PASSIVE** mode and the connector's real `GemHostHandler` connects
  ACTIVE, over a socket, through both libraries' codecs — S1F1/F2, S1F11/F12, S1F3/F4,
  S2F29/F30, S2F13/F14, S5F5/F6. The equipment is seeded with custom SVs / ECs / alarms
  so an assertion cannot pass on secsgem's built-ins alone.

  **Two harness findings, recorded rather than papered over.** `GemEquipmentHandler`
  does not survive repeated lifecycle in one interpreter: sharing one across tests failed
  non-deterministically (`WrongSourceStateError: Invalid source state for transition
  'select': COMMUNICATING (expected NOT_COMMUNICATING)` — it had not returned to
  NOT_COMMUNICATING before the next ACTIVE connect landed), and building a fresh one per
  test *hung the interpreter* on teardown. The equipment therefore gets its own process,
  the same shape the energy repo's DNP3 live test uses for the same class of reason.
  Whether real fab equipment shows the reconnect behaviour is **待核实** — HSMS has a T7
  "not-selected" timer precisely because a tool needs time to clean up a dropped
  selection, so it is plausible, and equally plausible that it is specific to secsgem.
  Nothing is asserted either way.
- **MTConnect now has a real HTTP agent** (`tests/test_mtconnect_live.py`).
  `test_mtconnect.py` monkeypatches `_http_get`, so the XML parsing was genuinely
  exercised but **the HTTP layer never ran**: the agent URL composed from host/port, the
  `/sample?from=&count=` query string, the streamed body read, and — the part that matters
  — two controls that exist *only* in the transport:

  - the **DTD/entity guard** (XXE / billion-laughs defense), applied to the FIRST streamed
    chunk so a hostile agent cannot make us read megabytes before we notice the `DOCTYPE`;
  - the **response size cap**, which refuses a body over `MAX_RESPONSE_BYTES` *while
    reading* rather than buffering it whole first.

  A mock handing back a finished string can demonstrate neither. Also covers
  `mtconnect_stream`'s long-poll against a server with a real sequence cursor, including
  the `instance_changed` stop — an agent restart renumbers sequences, so a held `from`
  cursor would otherwise attribute someone else's observations to this run.

  Needs only `requests`: no container, no root, no external agent.

  Mutation-verified, and the first version of the DTD test **failed that check**: it
  passed with either guard removed, because `_fetch_xml` re-checks the full body. It
  proved the defense existed *somewhere*, not that the early one worked. The replacement
  serves a `DOCTYPE` followed by an oversized body — only a guard that runs before the
  body is consumed can report the DTD, since otherwise the size cap trips first. That one
  does fail when the first-chunk guard is removed. *A control asserted only against a stub
  is a control you have not tested* — including when the stub is your own test server.
- **Modbus TCP now has a real wire** (`tests/test_modbus_tcp_live.py`). Modbus **RTU** has
  had one since the socat/PTY test; Modbus **TCP** — by far the more common transport in
  the field — had none. Every TCP test monkeypatched `_build_modbus_client`, so the code
  that assembles and parses the **MBAP header** (transaction id / protocol id / length /
  unit id) had never moved a byte. Sharing the read ops with RTU does not mean sharing the
  transport: MBAP and CRC framing are different code.

  A real `pymodbus` `ModbusTcpServer` on a loopback port, seeded with two deliberately
  different banks, reached through the ordinary `TargetConfig` path with nothing patched.
  Ten tests: the four read paths, float32 decode, a non-zero start address (the classic
  off-by-one, invisible against a mock that ignores the address it was handed), and three
  that only mean anything against a device —

  - **`modbus_apply_template` reads the register file it declares.** A template says
    whether its registers live in the holding or input file. A mock has one bank, so a
    wrong function code still "works" there; here the banks differ, and the oracle is the
    *same pure decoder* fed the declared bank, so any difference is the transport choosing
    wrong rather than a disagreement about decoding. The seeded window is 80 registers
    rather than a convenient 20 because the built-in templates that declare the **input**
    file are the wide ones — a template test that only ever exercises `holding` cannot
    catch a wrong function code, and the test asserts that both files were covered.
  - **`modbus_health_summary`** opens its own session and reads address by address — a
    different call shape from the block reads.
  - **an out-of-range read teaches rather than fabricates.** A real server's "illegal data
    address" exception must surface as an actionable error, never as a value. Fabricating
    would put an invented number in front of someone deciding whether to touch a live
    process.

  Needs no socat, no root and no container, so unlike the RTU test it runs everywhere
  including macOS. Verified by mutation: forcing the function code, shifting the template
  base, and an off-by-one on the register address each turn it red.
## 0.20.3 — 2026-08-01

> **Two governance invariants that reported the wrong thing, and three tests that had
> quietly stopped covering anything.** A call that failed was audited as a success — and
> the pattern circuit breaker was told the same, so an armed pattern that failed every
> time could never trip. And the runaway guard, whose job is catching stuck loops, was
> blind to the most likely loop of all: a caller retrying a denial forever. Both are now
> enforced by contract tests over the real tool surface rather than by comment.

### Changed
- **Three binding-contract tests stopped skipping.** The IoTDB `Session` surface and the
  Parquet export path skipped on every gate run because `iotdb` and `export` were not in
  the synced extras — both are pure wheels costing seconds, and both cover code this repo
  ships, so the skip was coverage we claimed and did not have. The gate now syncs them.

  The third, `taospy`'s native `taos`, dlopen()s **libtaos** at import time and skipped
  even in the integration-contracts job, which had `tdengine` installed — the Python
  package alone proves nothing without the C client, and the client is not on PyPI. That
  job now installs it from the vendor tarball, pinned by version **and sha256** (a
  third-party binary entering the build may not float), extracting just the driver rather
  than running the vendor's root-level install script.

  Verified on a Linux host with all three present: `1726 passed, 2 skipped`, the two
  remaining being the in-suite BACnet test (covered by the separate two-IP harness step)
  and an inverse skip that is correct when pyarrow *is* installed.
### Fixed
- **The runaway guard could not see the most likely runaway: a retried denial.** The
  budget does two different jobs, and a policy denial separates them — the **ceilings**
  (calls, wall-time) price work, while the **runaway guard** detects a stuck loop. A
  denied call is deliberately free of the ceilings: it did no work, and charging it would
  let a misconfigured deny rule exhaust an operator's budget without a single operation
  running. But the runaway fingerprint was recorded on that same allowed-only path, so a
  caller that does not understand a denial and retries it forever — the archetypal stuck
  loop, and the one an LLM agent is most likely to produce — could repeat without limit.

  Measured before the fix: **500 identical denied high-risk writes against a call ceiling
  of 10 produced zero stops**, and 500 audit rows.

  A denial is now charged to the runaway window, and only to the window. Once it fills,
  the guard's `BudgetExceeded` replaces the denial — the more actionable of the two, since
  at that point the caller needs "stop re-calling", not a 26th "denied" — and audits as
  `budget_exceeded`, so an operator can tell *"you were denied"* from *"you were denied
  and would not stop asking"*. A single denial stays free, and the ceilings still ignore
  denials entirely; both are pinned by tests.

  Hooked around `_pre_check` rather than at each `raise PolicyDenied`, so the three
  existing denial paths — and any future one — are covered by construction.
- **A failed call was audited as a successful one — and the circuit breaker was told the
  same.** Tools do not raise: `tool_errors` sits *inside* `@governed_tool` and converts
  every exception into the canonical `{error, hint}` envelope, so the governance wrapper
  saw an ordinary return value and recorded `status='ok'`. Two consequences, and the
  second is the one that bites:

  - the audit trail — this product line's compliance evidence — could not distinguish
    *"wrote 5 to DB1"* from *"tried to write and the PLC was unreachable"*. Both read `ok`;
  - `_finalize` reports `success=(status == 'ok')` to the pattern circuit breaker, so an
    armed pattern that failed **every** time was reported as succeeding every time. The
    breaker was blind to precisely the failures it exists to trip on.

  `_annotate_result` now recognises the envelope and records `status='error'`, and skips
  the undo computation for a call that changed nothing. Detection is deliberately narrow —
  only the two structural shapes the envelope takes (a dict, or a single-element list of
  one) and only when `error` holds a non-empty string, so a diagnostic tool returning
  `error: None`, an `{code, text}` object, or a multi-row result that includes one error
  row is left alone. The `str` shape is *not* sniffed: `"Error: ..."` is prose, and a
  prefix match would misread a legitimate string result.

### Added
- **Approval-gate contract over the real write surface**
  (`tests/test_write_approval_contract.py`). The gate was well covered against *synthetic*
  `@governed_tool` functions and a *synthetic* CLI command, but nothing drove the ten
  registered high-risk MCP write tools — the surface a client actually calls. A tool that
  lost its `risk_level="high"` in a refactor would have kept every existing test green;
  verified by mutation (downgrading `s7_write_db` to `low` now fails three tests).

  Each tool is driven three ways: **no approver → denied *and the connector is never
  reached*** (the second half is the assertion that matters — "it raised" only proves an
  exception, not that nothing reached the device); **approver recorded → the body runs**
  (without which the suite could pass by denying everything, which is a brick, not a
  gate); **dry-run preview → runs with no approver and audits at `low`**, since a gate that
  also blocked previews would teach operators to skip the preview and go straight to the
  write. A coverage assertion fails the build if a new write tool is not added to the table.

- **Audit-status fidelity tests** (`tests/test_audit_status_fidelity.py`) pinning both
  edges of the detection above, plus the two consequences: a failed write records no undo,
  and the circuit breaker is told the call failed.

## 0.20.2 — 2026-07-31

### Fixed (packaging)
- **`pip install iaiops[opcua]` resolved to a combination that installs cleanly and breaks
  at runtime.** asyncua asks for `pyOpenSSL` unbounded. A fresh resolve prefers the newest
  `cryptography` (50.x), which no modern pyOpenSSL accepts — 26.3 caps it at `<50` — so the
  resolver backtracks pyOpenSSL to **22.0.0**, a 2022 release whose bounds are loose enough
  to "fit" and whose bindings then fail against cryptography 50 at import
  (`AttributeError: module 'lib' has no attribute 'GEN_EMAIL'`). Any OPC-UA certificate /
  security-policy path breaks. It dragged asyncua itself down to 1.1.0 as well.

  The extras now floor `pyopenssl>=25` as an explicit **resolver guard** (not a dependency
  of this package), which keeps cryptography at 49 and asyncua at 1.1.8. Caught by the
  `integration contracts` CI job, which deliberately installs **unpinned** — it resolves
  what a user installing today gets, not what the lockfile froze. The lockfile-based gate
  job was green throughout, which is exactly the blind spot that job exists to cover.

> **Two governance invariants that were true in prose and false in code.** A credential
> passed to one of the three egress tools was written into the audit log verbatim and
> forwarded to SIEM — the redaction mechanism worked, nothing checked that tools used it.
> And `mqtt_publish` was exempted from the undo requirement because "a published message
> cannot be unsent", a claim true of a transient publish and wrongly applied to a retained
> one, which overwrites durable broker state. Both are now enforced by contract tests over
> the whole tool surface rather than by a comment.

### Fixed
- **A retained `mqtt_publish` is reversible, and now records the inverse.** `mqtt_publish`
  was the one high-risk write exempted from the undo requirement, on the documented
  grounds that a published message cannot be unsent. That is true of a **transient**
  publish and false of a retained one: `retain=True` REPLACES the broker's retained
  message on that topic — durable state every later subscriber receives — and the payload
  it replaced is readable beforehand and restorable after. The blanket claim had been
  applied to the whole tool, so a retained overwrite of a live setpoint left nothing to
  roll back to, in the one product line whose selling point is rollback.

  A retained publish now captures the prior retained payload first (returned as `before`,
  the same BEFORE-state contract `s7_write_db` and the other eight protocol writes follow)
  and records an undo descriptor. When nothing was retained, the inverse is a zero-byte
  retained publish — how MQTT clears one. The undo still returns `None` — "no safe
  inverse" — for every case that genuinely has none: a transient publish, a failed
  capture (never read as "there was nothing", which would make the inverse delete a
  retained message the operator did set), and a non-UTF-8 prior payload such as a
  Sparkplug protobuf, which cannot round-trip through the `str` payload parameter. An
  inverse that over-promises is worse than none, because someone will replay it onto a
  live broker.

  `WRITE_TOOLS_WITHOUT_UNDO` in `tests/test_smoke.py` is now **empty**: all ten
  high-risk writes declare an undo. Verified against a real mosquitto broker through the
  full paho loop (`tests/test_mqtt_retained_undo.py`) — seed, overwrite, apply the
  recorded inverse, confirm the broker holds the original again — which runs in CI, where
  the gate job already stands a broker up.

- **Security: three egress tools wrote their credential into the audit log in the clear.**
  `stream_publish` / `stream_publish_event` (`token`, a NATS auth token) and
  `historian_push` (`password`, the TSDB password) never declared those parameters in
  `sensitive_params`, so `@governed_tool` bound them into the audit row verbatim — and
  `audit_forward` then shipped that row to whatever SIEM is configured. The credential
  therefore left the box twice: once at rest in `~/.iaiops/audit.db`, once over the
  forward. Reproduced end-to-end before the fix (the row read
  `{"token": "SUPER-SECRET-TOKEN", ...}`), and a **failed** publish audits too, so an
  unreachable broker leaked just as readily as a working one.

  The redaction mechanism was never broken and needed no change — the CLI twin of the same
  operation (`iaiops historian push`) has always declared `@audit_sensitive("password")`
  and redacted correctly. What was missing was anything that noticed when an MCP tool
  forgot to. Rotate any NATS token or historian password that has been passed to these
  three tools, and check existing audit rows / SIEM indexes for it.

### Added
- **Credential-redaction contract test over both front-ends**
  (`tests/test_credential_redaction_contract.py`). Every registered MCP tool and every
  registered CLI command is scanned for parameters whose name says "credential"
  (`password` / `token` / `secret` / `api_key` / …); any that is not declared in
  `sensitive_params` fails the build. Detection is name-based and deliberately crude — it
  cannot know a parameter holds a secret, only that the name says so. The asymmetry is the
  right one: a false positive costs one justified line in `_REFERENCE_NOT_SECRET` (today:
  `secret_name`, a lookup key into the encrypted store, where redacting would blind the
  audit trail and protect nothing), a false negative costs a credential in a log that
  leaves the box. Two runtime proofs sit alongside the static scan — one per front-end —
  asserting the secret really is absent from the written audit row.

### Changed
- The CLI governance wrapper now re-exposes `_sensitive_params`. `functools.wraps` copies
  the *original* callback's `__dict__`, so a command's `@audit_sensitive` declaration was
  invisible from outside the wrapper. Redaction was unaffected (the inner governed callable
  is what audits), but an auditor — or the contract test above — reading the registered
  command would have concluded it declared no credentials at all.

## 0.20.1 — 2026-07-29

> **The read/write distinction is now machine-readable.** Until this release the
> only place a client could learn that `s7_write_db` writes to a PLC and
> `opcua_browse` does not was the docstring tag `[READ]` / `[WRITE]` — text for a
> human. Every tool now carries the MCP `ToolAnnotations` hints, **derived** from the
> `@governed_tool` harness rather than hand-written, so a client can put a confirm
> prompt in front of a plant write without knowing anything about OT. They are hints,
> not a gate: authorisation stays the caller's call and enforcement stays in
> `@governed_tool` (decision records D1/D3/D4).

### Added
- **MCP tool annotations, derived from the governance harness.** Every registered tool now
  ships the four MCP `ToolAnnotations` hints (`readOnlyHint` / `destructiveHint` /
  `idempotentHint` / `openWorldHint`), so a client can tell a browse from a plant write
  *programmatically* instead of parsing the `[READ]`/`[WRITE]` docstring tag a human reads.
  A Claude Desktop-style client can put a confirm prompt in front of the ten destructive
  tools (across the full surface — eight in the `factory` profile) without knowing anything
  about OT.

  The hints are **derived, not hand-written**: `@governed_tool` already records
  `_risk_level` / `_egress` / `_preview_param` / `_idempotent`, and `mcp_server/hints.py`
  maps those onto the annotations. `@mcp.tool()` is the outermost decorator on every tool, so
  a `FastMCP` subclass (`_GovernedFastMCP` in `mcp_server/_shared.py`) applies the derivation
  once for all ~170 registration sites. Hints therefore cannot drift from the governance they
  describe, and a tool is annotated the moment it is governed. An explicit `annotations=`
  argument still wins.

  `readOnlyHint` is deliberately narrow — low risk **and** no preview/dry-run parameter
  (having one means the tool has a real write mode) **and** no egress. That last clause is why
  the four egress tools (`historian_push`, `rca_narrate`, `stream_publish`,
  `stream_publish_event`) are neither read-only nor destructive: they ship plant data to a
  caller-named destination without touching a device.

  **These are hints, not a gate.** The MCP spec says annotations must not be relied on for
  security decisions, and this repo agrees — authorisation is the caller's call and the tap's
  guarantee is un-bypassable audit (decision records D1/D3/D4, the same reasoning that removed
  the `IAIOPS_READ_ONLY` gate in 0.19.0). Enforcement stays entirely in `@governed_tool`.
  Tool surface is unchanged (factory profile: 134 before and after).

  `idempotentHint` is left **unset** unless a tool positively declares `idempotent=True`
  (none does today). Asserting `False` everywhere would claim "calling this twice differs
  from calling it once" with no basis, and it leans the wrong way for the protocol writes.
  `openWorldHint` is the one hint **asserted rather than derived** — always `true`, the spec
  default and the conservative direction. A minority of tools are genuinely closed-domain
  (`protocols_supported`, `sparkplug_decode_payload`, the template listers); telling them
  apart needs a `closed_world` declaration on `@governed_tool` that does not exist yet.

  New contract tests (`tests/test_mcp_tool_hints.py`) walk the full registered surface and
  assert every tool is annotated, every hint is re-derivable from its decorator, the
  destructive set equals the high/critical-risk set exactly, and no `[WRITE]`-tagged tool
  claims `readOnlyHint`.
- **Margo descriptor schema gate** (CI job `margo-descriptor`, `scripts/margo_validate.sh`).
  `deploy/margo/margo.yaml` is machine-read by an orchestrator we do not control, and nothing
  checked it — a typo'd field or a dropped enum shipped silently and surfaced as a deployment
  failure at a site. It now validates against Margo's published `margo.org/v1-alpha1` LinkML
  schema on every PR. Both descriptors (this repo and `iaiops-energy`) pass clean.

  The schema and Margo's own valid/invalid examples are **vendored** under
  `deploy/margo/schema/`, pinned to upstream commit `c198139` — `pre-draft` is a moving branch
  (it changed the day before vendoring), so a live fetch would turn an upstream edit into a red
  build on an unrelated PR and would make the gate unrunnable offline. Drift is reported by an
  advisory `continue-on-error` step instead. The upstream **invalid** examples are validated too
  and must be rejected: a validator that has quietly stopped discriminating would pass our
  descriptor just as happily as a working one.

  **This is not a compliance claim, and the honest status in `docs/MARGO-ALIGNMENT.md` is
  unchanged.** The Margo compliance test suite *cannot* be run today — it does not exist (no
  conformance repo in the `margo` org; the PM group was still scoping a first PR1 vertical slice
  as of 2026-01-15). Structural validity of the descriptor is what is checkable now, and it says
  nothing about deployment behaviour, device-side runtime, or management-interface interaction.

## 0.19.0 — 2026-07-21

> **Read/write authorisation is not the tap's job — audit is.** The
> `IAIOPS_READ_ONLY` registration gate is **removed**. Encoding "this server may
> not write" by hiding tools put an authorisation decision inside the data tap;
> that decision belongs to the caller (agent judgement / account & permission
> management). The tap's guarantee is instead **un-bypassable audit on both
> front-ends** — and this release closes the gap that made read-only look
> necessary: the CLI used to call `ops.*` directly, so a CLI write left **no audit
> row**. Both surfaces are now governed at their own boundary, sharing one audit
> DB / policy / budget engine. `IAIOPS_NO_EGRESS` is untouched — a separate
> data-exfiltration / airgap axis, not authorisation.

### Removed
- **`IAIOPS_READ_ONLY` registration gate** (`mcp_server/readonly.py` and
  `tests/test_read_only_gate.py`) and every reference to it (server wiring,
  `server.json`, `protocols_supported` posture, README, ROADMAP). Write tools are
  exposed and **governed**, not withheld; whether a write is authorised is the
  caller's call. Writes remain high `risk_tier`, MOC-gated, dry-run-by-default,
  and undo-captured. See `docs/HLD.md` (decision record D1/D3/D4).

### Changed
- **Effect-based risk for writes, on BOTH surfaces.** `@governed_tool` gains an
  opt-in `preview_param` (+ `preview_truthy`): a preview/dry-run call — one that
  changes no state — audits and gates at `low` (no approver) even on a `high`
  tool, while the real write keeps the declared `high`. The ten MCP write tools
  opt in with `preview_param="dry_run"`, and the seven CLI write commands with
  `preview_param="apply", preview_truthy=False`. So a **dry-run preview no longer
  needs a recorded approver** on either front-end, but the real write still does.
  The parameter defaults off, so tools that do not opt in — and the sibling
  `iaiops-energy` / `iaiops-enterprise` repos that share this decorator — keep
  exactly today's behaviour until they adopt it.

### Added
- **CLI is audited on the same footing as the MCP server.** Previously
  `@governed_tool` sat only on the MCP wrappers, while the CLI called `ops.*`
  directly — so a CLI write (`iaiops ethercat write-sdo --apply`, `iaiops modbus
  write`, …) executed with **no audit row**. A central pass
  (`iaiops/cli/_govern.py`, run once at app assembly) now governs **every**
  registered Typer command, so a command cannot ship ungoverned by omission
  (`tests/test_cli_audit.py` pins 100% coverage). The seven CLI write commands use
  **effect-based risk**: a dry-run preview (`--apply` omitted) audits at `low` —
  it changes nothing, so it needs no approver — while the real `--apply` write is
  `high`, **approver-gated** (`iaiops approve`) and audited. So the CLI is no
  longer a governance backdoor around MOC, yet previewing a write stays friction-
  free. Credential-bearing commands (`secret set`, historian `push --password`)
  redact the secret from the audit row.
- **`docs/HLD.md`** — the missing authoritative architecture doc (4-layer design,
  governance spine, "audit on both MCP + CLI surfaces" principle, posture gates,
  decision record). `CLAUDE.md`'s dead `docs/PLATFORM-ARCHITECTURE.md` pointer is
  folded in.
- **`iaiops/core/sink/historian_read.py`** — the historian READ logic (`query` /
  `coverage`), extracted from `mcp_server/tools/historian_tools.py`. Both the MCP
  tools and the `iaiops historian query|coverage` CLI commands now call this core
  function at their own governed boundary. Previously the CLI commands imported
  and called the `@governed_tool`-decorated MCP bodies, so once the CLI itself
  became governed a single `historian query` produced **two** audit rows and
  **two** budget decrements (the runaway guard would trip at half the configured
  volume). Now governed exactly once per surface; the CLI no longer imports
  `mcp_server`. (`tests/test_cli_audit.py::test_delegating_cli_command_audits_exactly_once`.)

## 0.18.1 — 2026-07-20

> **Path-handling hardening.** Two tools wrote to a caller-supplied `out_path` without the
> traversal guard the repo already had and already applied elsewhere. Found by a follow-on
> question rather than a report: since 0.18.0 made `medium` count as a write, *do any
> `low` tools persist state?* Two do — both write a local file, which is correctly neither
> a control-path write nor egress. The classification held; the path handling did not.

### Fixed
- **Two tools wrote to a caller-supplied path without the shared traversal guard.**
  `alarm_rationalization_worksheet` and `export_data` took an `out_path` and wrote to it
  after only an ad-hoc check (`alarm_rationalization_worksheet` verified the parent
  existed; `export_data` checked nothing beyond `expanduser()`), while
  `compliance_report` and the evidence zip export already routed the same kind of
  argument through `validate_output_path`, which rejects `..` traversal and enforces the
  extension.

  That inconsistency matters under this repo's own threat model: `out_path` is free text
  chosen by the **caller**, and the caller is assumed to be a weak, local, or
  prompt-injected model — the same reasoning that withholds `rca_narrate` under
  `IAIOPS_NO_EGRESS` because its `base_url` is caller-chosen. An unvalidated write path
  let a confused model overwrite a dotfile or a config with CSV. The guard already
  existed; it simply was not applied.

  `export_data` now validates against the **chosen format's** extension, so a
  format/extension mismatch (a `.csv` holding parquet bytes) is refused too.

  **Behaviour change:** `alarm_rationalization_worksheet` now **creates** a missing
  parent directory (mode `0700`) instead of raising. That is what the other two
  `out_path` tools already did; three tools taking the same argument should not answer
  the same input three different ways.

### Added
- **CI gate for caller-supplied output paths** (`tests/test_output_path_guard.py`) — an
  AST scan that finds every MCP tool taking an `out_path` and asserts it routes through
  the shared validator, so the next file-writing tool is caught by the suite rather than
  by a reviewer noticing. `compliance_evidence_bundle` is allowlisted because it
  delegates validation one hop down; following the repo's existing facade pattern, that
  exemption is **corroborated against the delegate's real source**, so a refactor moving
  the guard out of `evidence.py` fails the gate instead of silently widening the
  exemption.

## 0.18.0 — 2026-07-19

> **Read-only means read-only.** A one-fix release for the gate's *selection* rule, with
> no change to this package's own surface. It exists because the follow-on audit of
> `iaiops-enterprise` found `IAIOPS_READ_ONLY=1` there withholding **nothing** — 9 tools
> in, 9 tools out — while serving the two tools that mint OT write authority. Verified
> against the published 0.17.0 wheel, not inferred.

### Fixed
- **`IAIOPS_READ_ONLY` now withholds `medium`-risk tools, and anything it cannot
  classify.** Two changes to the gate's selection, no change to iaiops' own surface
  (verified: `factory` 134→126, `all` 147→138, `building` 93→91 — identical to 0.17.0,
  because this package has no `medium` tool).

  1. **`medium` is a write.** 0.17.0 deliberately left it out and let a test force the
     decision the day a medium tool appeared. It appeared in `iaiops-enterprise`:
     `approval_approve` — whose n-th distinct approver **mints the token that authorises
     an OT write** — and `approval_approvers_set`, which rewrites *who may approve*
     (passing `[]` reopens approval to anyone). A read-only server that still hands out
     write authorisation is a contradiction: it cannot touch the PLC itself, but it can
     issue the credential that lets something else do it, and the audit trail will show a
     perfectly legitimate approval. Reclassifying those tools to `high` would have been
     the wrong fix — in this family `high` means "MOC-gated, needs a recorded approver",
     so a `high` `approval_approve` is circular. The honest classification is `medium`,
     so the gate had to learn that `medium` is a write.
  2. **Selection is now an allowlist** (`READ_RISK_LEVELS = {"low"}`) instead of a denylist
     of write levels. A tool whose level is unrecognised — a new level, a typo like
     `"hgih"`, one never set — is now **withheld** rather than served. The previous
     behaviour deferred to `assert_all_tools_governed`, but that only asserts the
     `@governed_tool` marker is present, not that the risk level is one the gate
     understands, so a typo'd level passed governance *and* got served by a read-only
     server. A read-only site noticing a missing read tool is a cheap, visible failure;
     serving one unclassifiable tool as if it were safe is not.

  `WRITE_RISK_LEVELS` is still exported and still names the state-changing levels; it now
  contains `medium`. Downstream packages that run their own MCP server (`iaiops-energy`,
  `iaiops-enterprise`) inherit both changes as soon as they pin this version.

## 0.17.0 — 2026-07-19

> **Weak / local-model hardening.** Field reports from an air-gapped PoC driving an
> MCP server with a local Llama 3.3 70B ([VMware-AIops#31](https://github.com/zw008/VMware-AIops/issues/31))
> showed an operator compensating with ~17 hand-written prompt guardrails — "work
> read-only", "never invent objects", "mark absent fields not-available", "don't claim
> no data was returned". Every one of those is a **harness** gap dressed up as a prompt.
> A guardrail the next operator forgets to paste is not a guarantee, and on an OT line
> the failure mode is not a bad answer — it is a write to a live PLC, or an operator
> told the plant is healthy because a capped alarm list read as empty. Both are fixed
> here in the server, where they hold regardless of which model is driving.

### Added
- **Read-only registration gate (`IAIOPS_READ_ONLY=1`)** — every `high`/`critical`
  (write) tool is removed from the FastMCP registry *before the server serves*, so it
  never appears in `list_tools()`. A **registration-time** guarantee, not a call-time
  refusal: a weak, local or prompt-injected model can call any tool it can *see*, and a
  stray OT write is physically irreversible — a tool absent from the registry cannot be
  hallucinated into a call at all. Verified across all 11 named profiles: writes go to
  **0** in every one, covering all 10 write tools including the edition-scoped
  `bas_command` (`factory` 134→126, `all` 147→138, `warehouse` 93→90). The gate **fails
  closed** — if the registry cannot be introspected the server refuses to start rather
  than serve write tools to an operator who asked for none — and it reuses the existing
  `@governed_tool(risk_level=…)` metadata, so no tool needed reclassifying. `medium` is
  deliberately *not* treated as a read: no MCP tool uses it today, and a test fails if
  one appears, forcing the call to be made explicitly rather than by default.
  `protocols_supported` survives and **reports the read-only state**, so the model is
  told rather than left to infer it from absent tools.
- **No-egress registration gate (`IAIOPS_NO_EGRESS=1`)** — a second, **orthogonal**
  switch: "nothing leaves this box". Same mechanism (removal from the FastMCP registry
  before serving, fails closed, pure narrowing pass), different predicate. It withholds
  the 5 tools whose purpose is transmitting local/plant data to a destination the
  *caller* names: `stream_publish` / `stream_publish_event` (NATS bus), `historian_push`
  (external TSDB), `mqtt_publish` (broker), `rca_narrate` (POSTs the RCA verdict — plant
  tags, values, citations — to a caller-supplied model `base_url`). Two gates rather
  than one widened gate because the questions are genuinely different: `historian_push`
  is `risk_level="low"`, it changes no plant state, so the read-only gate *keeps* it —
  yet it ships telemetry off-box, meaning a "read-only" server without this switch still
  exfiltrates. `mqtt_publish` is both a control path and an egress path, and either gate
  alone withholds it. Measured on the real registry, governance assertion green in all
  four combinations: `factory` 134 → 126 (read-only) / 129 (no-egress) / **122** (both);
  `all` 147 → 138 / 142 / **134**; `building` 93 → 91 / 89 / **87**. The gates compose in
  either order — both are pure filters over independent predicates.
- **`@governed_tool(egress=True)`** — a new, optional keyword recording the fact on the
  tool itself, alongside the existing `risk_level`. The gate reads *metadata*, never a
  hardcoded name list: a name list is what would let the next egress tool escape
  silently. Backward compatible by construction — the default is `False` and a tool
  decorated by an older copy of the harness simply has no `_egress` attribute, which
  readers must treat as `False`, so `iaiops-energy` and `iaiops-enterprise` are
  unaffected until they opt in.
- **One return envelope for every bounded result** (`iaiops/core/runtime/envelope.py`) —
  a model reading raw JSON cannot tell a *short* list from a *truncated* one. Every
  bounded return now carries five keys, always: `items_returned`, `items_total`,
  `items_total_is_exact`, `is_truncated` (a plain bool — never a string, never a nested
  dict) and `truncation_note`. A `limit + 1` probe reports `items_total` as an explicit
  **null** rather than passing the page size off as the total. Two supporting rules ship
  with it: `with_explicit_nulls()` renders a requested-but-absent field as an explicit
  `null` (an omitted key is a hallucination licence — the next best guess fills the
  hole), and `enum_passthrough_violations()` makes "raw OT enums pass through verbatim"
  assertable, so severity `800` never becomes "High" and `BAD_NOT_CONNECTED` never
  becomes "bad". Migrated all 10 bounded returns across sparkplug, alarm-flood,
  baseline-store, maintenance-log, PLC-program outline, alarm/compliance/historian/
  plc-program tools.
- **CI gates for all three**, so the *next* tool is caught by the suite rather than by a
  reviewer noticing: an AST scan asserts that any function emitting a truncation flag
  builds the envelope through the shared helper (empty allowlist on purpose — an
  exemption should have to be argued for in review), a generalized invariant test
  asserts no write tool can reach a read-only server, and a second AST scan
  (`tests/test_egress_gate.py`, empty allowlist) asserts that any MCP tool *reaching* a
  transport declares `egress=True`. That last one derives which functions transmit by
  scanning `iaiops/` for send primitives on fully-qualified names — bare names like
  `send` / `write` / `execute` collide across the codebase — and adds three declared
  multi-hop facades (`core.egress`, `core.sink.push`, `core.llm`), each carrying a
  written justification *and* a `transport_root` checked against source, so a transport
  refactored out of a declared tree fails the gate instead of leaving a stale prefix
  matching nothing. All three gates guard *themselves* (they assert their own predicates
  fire on a known-bad snippet), so a refactor that broke the matching cannot leave them
  passing vacuously.

### Compatibility
- The envelope keys are **purely additive**. The published `truncated` key already had
  three different types — a string (`maintenance_log`), a per-section dict
  (`alarm_flood_report`), a bool everywhere else — and that inconsistency is precisely
  the hazard being fixed. Retyping a published key would break consumers, so every
  legacy key is left byte-identical and the envelope is added alongside; `is_truncated`
  is the one key a reader should trust.
- `IAIOPS_READ_ONLY` and `IAIOPS_NO_EGRESS` are both **opt-in** and unset by default:
  existing deployments are byte-identical. Read-only means **no control-path write** and
  does not stop data leaving; no-egress means **no data leaving via an MCP tool** and
  does not stop writes. Neither implies the other; set both for a read-only sealed tap.
- `IAIOPS_NO_EGRESS` is **not a firewall**, and the README says so where an operator will
  read it. It gates MCP tools only — `iaiops audit forward` is a CLI path no registry
  gate can reach. Reads still open outbound sockets (iaiops is a network tap). And it
  never inspects arguments: a tool is present or absent as a whole, which is why a tool
  with a caller-supplied destination is withheld even when its default is localhost —
  under this threat model the *model* picks the argument. Local file writes are not
  egress, so `export_data` and `compliance_evidence_bundle` stay exposed.
- **Both gates apply to the `iaiops-mcp` server only** (and its per-protocol /
  per-edition entry-point shims). The `envelope` contract lives in
  `iaiops/core/runtime/`, so anything building on `iaiops.core` picks it up — but the
  two gates live in `mcp_server/` and are wired in *that* server's `main()`. In
  particular **`iaiops-energy-mcp` does not yet honour either switch**: it mirrors in
  the base brain/compliance tools and its own `register()` never applies the gates, so
  `IAIOPS_NO_EGRESS=1` there leaves `historian_push`, `rca_narrate`, `stream_publish`
  and `stream_publish_event` exposed (verified against its real registry — 59 tools).
  Setting the vars on `iaiops-energy-mcp` is silently ineffective today. Wiring the
  gates into `iaiops-energy` ships alongside this release as **`iaiops-energy` 0.1.7**
  (which pins `iaiops>=0.17` for exactly this reason); on 0.1.6 and earlier the
  switches are silently ineffective there. Documented rather than quietly left for an
  operator to discover, because a switch believed to be on is worse than one known to
  be absent.

## 0.16.0 — 2026-07-17

> **Protocol + intelligence depth release, tool surface unchanged.** Eight features that
> *deepen existing tools* rather than add new ones — the tool count is identical (no profile
> crosses the flood ceiling): EtherNet/IP PCCC (PLC-5 / SLC-500 / MicroLogix) + Micro800,
> MTConnect bounded long-poll streaming, Sparkplug B DataSet/Template rich decode, live-verified
> OPC-UA certificate security, predictive-maintenance RUL + waveform features, OEE Six Big
> Losses + energy/carbon analytics, an RCA causal-graph export, and ISA-18.2 alarm
> rationalization (suppression/first-out advice). Plus the earlier HART passive burst listener,
> SIEM auth-header shapes, and the IGEL Managed-Container refresh.

### Added
- **EtherNet/IP PCCC (PLC-5 / SLC-500 / MicroLogix) + Micro800** — the EtherNet/IP
  connector now selects the pycomm3 driver by a `plctype` field (config key or per-call
  arg on every `eip_*` tool): `logix` (default, ControlLogix/CompactLogix/GuardLogix
  symbolic tags — unchanged), `slc` (PCCC data-table addressing via `SLCDriver`: `N7:0`
  integer, `B3:0/0` bit, `F8:0` float, `T4:0.ACC`/`C5:0.ACC` timer/counter, `N7:0{10}`
  slice), or `micro800` (Micro820/850/870 symbolic variables via `LogixDriver`, IP-only,
  `init_program_tags=False`). No new tools — the existing five `eip_*` tools gained the
  selector. `eip_list_tags` returns the SLC **data-file directory** (there is no PCCC
  online symbol table) and `eip_controller_info` returns the SLC **processor type**;
  reads/writes and the write-undo work across all three families. Real PLC-5/SLC-500/
  MicroLogix/Micro800 hardware is **待核实** — the driver-selection, PCCC read/write and
  file-directory paths are exercised against a mocked pycomm3 `SLCDriver` only.
- **Predictive-maintenance depth (no new tool)** — the always-on `pdm_forecast` now returns three
  deeper, equally-explainable views on top of the Theil–Sen trend, all pure/stdlib-only:
  a **degradation pattern** (`gradual` vs `sudden` vs `cyclic` vs `irregular`, via transparent
  monotonicity / step-score / autocorrelation-period metrics, each cited); a **remaining-useful-life**
  `rul` block when degrading (linear *and* exponential extrapolation to the limit, an ETA confidence
  band from the slope IQR, and a fit-quality R² that picks the better model); and optional
  time-domain **waveform features** (RMS / kurtosis / crest factor / peak-to-peak / zero-crossing
  rate — bearing-fault impulsiveness) behind a new `include_waveform` flag. New pure helpers live in
  `iaiops/core/brain/pdm_math.py`, `pdm_features.py`, `pdm_rul.py`, `pdm_patterns.py` (fully
  unit-testable without a device). **Zero new `@mcp.tool`** — only the existing `pdm_forecast` was
  deepened, so no profile tool-count / flood-threshold change.
- **OEE / energy analysis depth (no new tools)** — the always-on `oee_compute` and
  `oee_multidim` tools gain deeper analytics with **zero** new `@mcp.tool` (the brain tool
  count is unchanged, so no profile crosses the flood ceiling). `oee_compute` now returns a
  **Six Big Losses** decomposition (`six_big_losses` in `iaiops/core/brain/oee.py`): a
  telescoping time-ladder attributing every second of planned time to fully-productive output
  or one of breakdown / setup / minor-stops / speed / startup-rejects / production-rejects,
  where each loss's `pct_of_planned` is exactly the OEE points it costs (the six shares sum
  with OEE to 1.0; an optimistic ideal cycle is flagged, not hidden). New pure
  `iaiops/core/brain/energy.py` adds **energy intensity** (kWh/unit), optional **carbon**
  accounting, and **actual-vs-baseline deviation** by shift/period — flagging anomalies by
  two explainable rules (fixed tolerance band + robust Iglewicz-Hoaglin MAD outlier). Wired
  into `oee_compute` (single run) and `oee_multidim` (per-dimension + cross-group). The carbon
  emission factor is a **caller-configurable** parameter; its default (0.5 kg CO2e/kWh) is an
  explicit placeholder surfaced with its source and marked `待核实` — no authoritative grid
  factor is baked in.
- **MTConnect incremental long-poll streaming** — `mtconnect_sample` gains stream mode
  (no new tool): pass `from_sequence` + `max_samples`/`duration_s` (+ optional `interval_ms`)
  and it polls `/sample?from=<seq>&count=<n>`, advancing by the Streams header's
  `nextSequence` each round to pull observations incrementally by sequence. Strictly
  **bounded** — stops on the first of max_samples / duration_s / `MAX_STREAM_POLLS` /
  caught-up / no-progress / agent `instanceId` reset (never an unbounded loop). This is
  client-side polling, deliberately **not** the agent's server-push multipart `interval`
  hold; `interval_ms` is client-side poll spacing. `mtconnect_current` and the snapshot
  `mtconnect_sample` now also return `next_sequence` (the resume cursor). Mock-tested against
  synthetic advancing/caught-up/reset agents; real MTConnect agent long-poll behavior `待核实`.
- **HART passive burst listener** — `hart_burst_listen` receives unsolicited HART-IP
  burst-publish messages (message type 2) on the session socket, the timed complement to the
  active `hart_burst_sample`; publishes decode through the same command-3 parser. Live gateway
  `待核实`. Hardened after review: a runt/garbage UDP datagram is skipped (not an abort), and a
  TCP timeout **mid-frame** raises a desync error instead of silently returning None (the
  consumed bytes would otherwise shift every later read on the stream).
- **SIEM forwarder auth-header shapes** — `IAIOPS_FORWARD_AUTH_SCHEME` (default `Bearer`;
  empty = raw token value) and `IAIOPS_FORWARD_AUTH_HEADER` (default `Authorization`) cover
  Splunk HEC (`Splunk <token>`), Elastic `ApiKey`, and `X-Api-Key`-style SIEMs.
- **IGEL overlay refreshed** — the Managed-Container route references the published,
  cosign-signed 0.15.0 image with the socket MCP transport; ready-to-paste submission answers
  in `deploy/igel/SUBMISSION.md`.
- **RCA causal-graph export (no new tool)** — the always-on RCA copilot can now emit its
  cited verdict as a structured **causal graph** for a frontend/Grafana via a new opt-in
  `include_graph` flag on the existing `downtime_root_cause`, `downtime_root_cause_live`, and
  `downtime_triage` tools (and `rca.downtime_rca`). It attaches a `graph` block —
  `{nodes:[{id, kind (signal|cause|symptom), label, score, …}], edges:[{from, to, weight,
  relation (supports|attributed_to)}], mermaid, meta}` — where a **signal→cause** edge weight
  is the evidence item's contribution score and a **cause→symptom** edge weight is the
  hypothesis confidence, both copied verbatim. It is a **pure re-projection of the
  already-computed verdict** (new module `iaiops/core/brain/rca_graph.py`): no new correlation,
  scoring, or inference; no orphan nodes, no fabricated edges; a thin/error verdict yields an
  empty graph. A paste-ready Mermaid string ships inline and `causal_graph_dot()` renders
  Graphviz DOT. **Zero new `@mcp.tool`** — only existing tools gained the flag, so no profile
  tool-count / flood-threshold change (factory stays 134). Omit the flag ⇒ byte-identical output.
- **Alarm-rationalization depth (no new tool)** — the always-on `alarm_flood_analysis` tool now
  returns three deeper ISA-18.2 views with **zero** new `@mcp.tool` (the brain tool count is
  unchanged, so no profile crosses the flood ceiling). New pure/stdlib-only functions in
  `iaiops/core/brain/alarm_flood.py`: an **alarm-load profile** (`alarm_load_profile` +
  `classify_alarm_rate`) bucketing annunciations per 10 min into ISA-18.2/EEMUA-191 rate bands
  (acceptable / manageable / over_target / flood) with the peak-load bucket, band distribution
  and a first-half-vs-second-half trend; **root-cause grouping** — each detected flood episode
  now names its **first-out** annunciation (earliest in the episode, a heuristic root cited by
  timestamp, not a causal claim); and **suppression/shelving advice** (`suppression_advice`)
  deriving a starting on-/off-delay (debounce) from observed cycle timing for chattering alarms
  and a time-limited shelve for standing alarms. The suppression advice is **advisory only**
  (`advisory_note`, restated on every row) — iaiops proposes deadband/delay/shelve *values* for
  human review and never applies suppression, shelving, or delay changes; adoption goes through
  the operator's ISA-18.2 / management-of-change process. Surfaced through the existing
  `alarm_flood_analysis` tool (new `load_bucket_s` arg) and the `iaiops diag alarm-flood` CLI.
- **OPC-UA certificate message security — validated end-to-end (no new tool)** — the existing
  application-certificate path in `iaiops/connectors/opcua/transport.py` (a `client_cert` +
  `client_key` target builds asyncua's `set_security_string`, optional `server_cert`) is now
  covered by a live in-process test (`tests/test_opcua_security.py`): a self-signed asyncua
  server that accepts **only** Basic256Sha256 secure channels is driven through the ops layer
  over the encrypted channel in **both Sign and SignAndEncrypt** modes — asserting the
  negotiated policy URI + message-security mode on the wire, that `server_cert` pinning *and*
  client-side auto-discovery both read, that anonymous is refused by the secure-only server,
  and that a no-cert target still connects anonymously (back-compat). The README OPC-UA entry
  moves from "roadmap, not validated" to this verified matrix; third-party / vendor-server
  interop, the other policies (Aes128 / Aes256 / Basic128Rsa15 / Basic256), server-side
  certificate-trust enforcement, and X509 *user* tokens stay `待核实`. No new `@mcp.tool` — no
  profile tool-count / flood-threshold change.
- **Sparkplug B DataSet / Template rich-type deep decode (no new tool)** — the existing
  Sparkplug decode path (`sparkplug_decode_payload`, `sparkplug_subscribe_sample`) now fully
  expands the two structured UNS datatypes instead of summarizing them. A **DataSet** metric
  decodes to columnar `{columns, types, rows}` — column `types` mapped from the DataType enum,
  and every row cell decoded through its governing column type so signed integers in the table
  sign-reinterpret correctly (with `row_count` / `truncated` reporting true vs returned size).
  A **Template** metric decodes to `{template_ref, is_definition, version, members, parameters}`,
  where `members` are `{name, type, value}` decoded **recursively** (a member that is itself a
  DataSet or a nested Template expands in place, bounded by `MAX_TEMPLATE_DEPTH` against
  pathological nesting) and `parameters` are type-aware `{name, type, value}`. New pure codec
  helpers (`_decode_dataset` / `_decode_template` / `_decode_parameter` / `_scalar_from_oneof`)
  in `iaiops/connectors/sparkplug/ops.py` are fully unit-tested from crafted protobuf fixtures
  (column-type mapping, row values, two's-complement cells/members/parameters, nested Template,
  depth guard). **Zero new `@mcp.tool`** — only existing tools/codec were deepened, so no
  profile tool-count / flood-threshold change. Real broker end-to-end DataSet/Template streams
  are **待核实** (verified against synthetic Tahu-schema payloads only, no live broker).

## 0.15.0 — 2026-07-15

> **Japan-gap + RCA-depth release.** CC-Link data becomes readable with zero new hardware
> (through the master PLC via SLMP), the RCA copilot gains a real per-site learning loop
> (CMMS work-order exports → labeled corpus → learned cause weights) and time-localizable
> alarm evidence (OPC-UA A&C events with server timestamps), the whole stack gets an
> air-gapped deployment story, and release artifacts are now cosign-signed. One real latent
> bug found and fixed en route: failed OPC-UA connects leaked a thread each.

### Fixed
- **Thread leak on every failed OPC-UA connect** (latent since the connector shipped) —
  asyncua's sync `Client` starts a non-daemon ThreadLoop in its *constructor*, and the
  session factory deliberately skips teardown when connect fails, so each unreachable-server
  attempt leaked one running thread: enough to keep a long-lived MCP server (or the test
  runner) from ever exiting. The OPC-UA session now tears the client down again when the
  connect raises (`_connect_opcua`); regression-tested.

### Added
- **Timestamped OPC-UA Alarms & Conditions** — `opcua_alarm_events`: a *bounded* A&C event
  subscription on the Server object (+ `ConditionRefresh`, so retained/active conditions are
  replayed with their original event `Time`); each event carries the server's own timestamp,
  severity and ACTIVE/RTN/EVENT state. The RCA evidence collector (`collect_evidence` /
  `downtime_rca_live` and the ISA-18.2 alarm tools' shared acquisition path) now tries this
  timed feed first and falls back to the untimed address-space scan — alarm evidence becomes
  time-localizable for the temporal weighting. Verified end-to-end against a real in-process
  asyncua server (third-party A&C servers `待核实`). Also fixed en route: asyncua's sync
  `Subscription` doesn't expose `subscription_id` (it lives on the wrapped aio object), and a
  server with no retained conditions answers `ConditionRefresh` with `BadNothingToDo` — both
  now handled.
- **Maintenance-log → RCA corpus bridge** — `rca_corpus_from_maintenance` MCP tool +
  `iaiops diag corpus` (CSV/JSON): normalizes a CMMS/work-order export into the labeled
  incident history `learn_cause_weights` consumes (explicit taxonomy cause → built-in
  EN/中文 synonym table, extendable per site → unambiguous keyword inference over free
  text). Rows it cannot map are returned with the reason — never silently guessed; signals
  come only from explicit columns or symptom text (no fabricated evidence). With
  `learn=true` the learned per-site `cause_weights` are included, ready for
  `downtime_root_cause`.
- **CC-Link family reads through the master PLC (zero CC-Link hardware)** — Phase 1 of the
  `docs/CCLINK.md` feasibility study, closing the biggest Japan-market gap via the existing
  `mc` connector (SLMP's message format = MC 3E frame). Three governed `[READ]` tools:
  `mc_cclink_templates` (documented default RX/RY/RWr/RWw ↔ PLC-device refresh layouts for
  classic CC-Link and CC-Link IE Field, `待核实` per project), `mc_cclink_link_read` (refresh
  image with per-project head-device overrides), and `mc_cclink_network_health` (per-station
  data-link status decoded from the master's link special registers — classic `SW0080–`, IE
  Field `SB0049` + `SW00B0–` + `SW00A0–` baton pass; RCA evidence). Live pass on a real
  master `待核实`.
- **Air-gapped operation guide + deployable stack** — `docs/AIRGAP.md` (three tiers; offline
  wheelhouse + offline model provisioning; zero-egress verification) and
  `deploy/airgap/compose.yaml` (signed iaiops image + pinned on-box Ollama on an
  internal-only network).
- **Signed release artifacts** — per-profile OCI images are cosign-signed and the Margo
  application package (`iaiops-margo-package-<version>.tar.gz` + `.sig`) is attached to
  each GitHub release; CI now waits for PyPI before building images (fixes the silent
  v0.12–v0.14 image-build failures).

## 0.14.0 — 2026-07-13

> **Audit-hardening release.** A six-dimension internal audit (security · protocol
> correctness · governance consistency · tests · docs honesty · code quality) drove a
> batch of real fixes: the endpoint-scoped approval path is restored, several connectors
> stopped returning wrong or fabricated values, the HTTP-layer connectors got a
> token-egress guard, the test suite now isolates its home + covers the full 166-tool
> surface and the previously-untested governance safety modules, and per-protocol dispatch
> was collapsed into one drift-guarded capability registry. No breaking API removals; some
> connectors now raise a teaching error where they previously returned a wrong value.

### Security
- **Endpoint-scoped approval was silently dead.** The governance layer resolved the
  approval/policy selector from `target`/`env`, but every MCP tool names it `endpoint`, so the
  scope was always empty — per-endpoint approval tokens could never be consumed (forcing operators
  onto unscoped tokens that authorized writes to *every* endpoint) and environment-scoped policy
  rules misbehaved. The selector now resolves `endpoint` too; a token scoped to one endpoint no
  longer authorizes another. (#63)
- **Token-egress guard for the HTTP-layer connectors (BAS controller + Gateway read layer).** A
  caller-supplied `base_url` + a stored `secret_name` could exfiltrate the bearer/API token to any
  outbound host. A new shared guard (`iaiops/core/runtime/url_guard.py`), enforced before any
  network I/O, requires `http(s)`, refuses credential-in-URL, and only sends a stored token to
  clearly-internal destinations unless the operator opts a host in via `IAIOPS_TOKEN_EGRESS_HOSTS`.
  (#69)
- **`verify_tls` can no longer be silently disabled by a tool argument.** `verify_tls=False` is now
  refused (before any I/O) unless the operator sets `IAIOPS_ALLOW_INSECURE_TLS=1`; secure default
  unchanged. (#69)
- **Audit hygiene.** Tool-parameter values are control-char sanitized before they enter the audit
  chain; syslog-forwarded audit records stay valid JSON when large (drop fields with a `_truncated`
  marker instead of a lossy byte-truncation); `change_limits` in `rules.yaml` is now enforced
  instead of warn-and-allow. (#65)

### Fixed — protocol read correctness (wrong/fabricated values → correct or a clear error)
- **Sparkplug B** signed integers (Int8/16/32/64) are two's-complement reinterpreted from the
  unsigned protobuf fields — a −5 metric no longer reads as a huge positive number; a node rebirth
  (NBIRTH, seq→0) no longer raises a false sequence-gap. (#66)
- **HART** no longer sends every command to a fabricated long address (healthy transmitters could
  never answer): a real identity→address discovery chain (or a configured `long_address`) is used,
  HART-IP responses are validated (type/id/sequence/status) instead of trusting the first datagram,
  and `iaiops doctor` grew a HART probe so a healthy HART endpoint no longer reports as failed. (#68)
- **Siemens S7** non-DB reads map every data type to its exact pyS7 token — 1-byte types
  (CHAR/USINT/SINT) no longer read overlapping 16-bit words, REAL/INT/DINT keep their sign, LREAL
  reads its full 8 bytes; an unknown memory area or data type now raises a teaching error instead of
  silently retargeting Merker memory. (#64)
- **FINS/TCP** closes its socket when the node-address handshake fails (was leaking a file
  descriptor per failed call in the long-lived server). (#64)
- **Modbus** honours the configured `timeout_s` (TCP + serial); a 32-bit decode over an odd register
  count reports a decode note instead of silently dropping data; `modbus_health_summary` gained an
  opt-in `int16` decode so bipolar tags aren't false-alarmed. (#66)
- **`diagnose_dataflow`** distinguishes a transport failure from a protocol exception response — a
  reachable Modbus PLC that simply doesn't map register 0 is reported as *alive*, not "network down".
  (#66)
- **EtherCAT** `ethercat_set_state` reports `reached=None` when the post-write state check fails,
  instead of echoing the never-observed prior state. (#64)
- **MTConnect** HTTP fetch streams with a 4 MiB response cap (was reading unbounded bodies into
  memory). (#68)
- **Connection routing** raises a teaching error for sessionless protocols instead of falling back
  to an OPC-UA session. (#64)

### Added
- **`warehouse` and `clinical` pip extras** so the documented `pip install iaiops[warehouse]` /
  `[clinical]` actually resolve (they map to the same protocol sets as the profiles); `hart` folded
  into the `all` extra. (#67)

### Changed
- Two lazy singletons (`_shared._manager`, `secretstore.open_store`) now use double-checked locking,
  closing a race under the SSE/streamable-HTTP transport (the KDF unlock could run twice). (#71)
- Tool-flood warning threshold raised 100 → 135 so the largest legitimate named edition (`factory`,
  129 tools) no longer warns on every launch, while the catch-all `all` (141) still does. (#71)

### Refactored
- Per-protocol dispatch (doctor probe/where, dataflow connect/read, monitor, CLI init, session
  routing) collapsed from ~7 parallel if/elif ladders into one authoritative capability registry
  (`iaiops/core/runtime/capabilities.py`) with an explicit "unsupported" sentinel and a drift-guard
  test, so a future protocol that forgets to register a capability fails CI loudly. Behavior
  preserved. (#73)

### Tests & CI
- New `tests/conftest.py` isolates `IAIOPS_HOME` per test (tests no longer write the developer's real
  audit chain) and resets the governance singletons; the write-tool contract set is derived
  dynamically (catches a missing `bas_command`); the governance contracts now cover the full 166-tool
  surface incl. edition tools; and the previously-untested `undo` / `budget` / `patterns` safety
  modules gained end-to-end tests. (#72)
- CI gate now runs `ruff format --check` (was `ruff check` only); the repo was reformatted to match.
  (#74)

### Docs
- Honesty pass: corrected overclaims (nonexistent extras, Micro800 / Modbus-write coverage that isn't
  implemented, a retracted IEC-104 loopback claim, the `server.json` default), fixed stale counts /
  dead links, and synced the en/zh READMEs. (#67)

## 0.13.0 — 2026-07-13

> **Two new read-only OT integration layers, above the field protocols.** A **BAS
> controller layer** (building edition) reads Metasys/Niagara supervisory REST above BACnet,
> and an **Ignition Gateway MES/SCADA read layer** (factory edition) reads the production
> surface OPC-UA doesn't cover — both edition-scoped, brand-isolated, reusing the shared HTTP
> stack with no new dependency. Line-wide governed tools **156 → 166** (156 read + 10 writes;
> the one new write, `bas_command`, ships default-off with a life-safety denylist).

### Added — Gateway MES/SCADA read layer (factory edition, READ-ONLY)
- **New `ignition` connector** (`iaiops/connectors/ignition/`) — a config-driven HTTP reader for the
  vendor SCADA/MES platform's **Gateway HTTP/web API**: the MES-ish production surface (module
  health, tag-tree browse, current tag values, active alarms, tag-history) that the base `opcua`
  connector does NOT cover. The platform also exposes an OPC-UA server, but that stays on the
  existing `opcua` connector — this layer deliberately does **not** reimplement OPC-UA. A small
  per-deployment **dialect** (`webdev` / `gateway`: resource paths + field aliases) folds each
  response shape into one neutral schema; reuses the shared `requests` stack (no new HTTP dep) and
  the `make_session` lifecycle, with the API token/key resolved from the encrypted secret store by
  key name. The vendor/product name stays inside the connector (brand-isolation).
- **New `ignition_tools`** (factory EDITION module) — `ignition_gateway_status`,
  `ignition_tag_browse`, `ignition_tag_read`, `ignition_alarm_status`, `ignition_tag_history` — **ALL
  READ, risk=low, NO writes** (the governed/read-only complement to the platform's own official MCP
  module, differentiated by the audit/budget/undo harness, not by writing).
- **`ignition` extra** (`pip install iaiops[ignition]`, reuses the MTConnect `requests` pin) folded
  into the `factory` bundle; support-version matrix rows added to the factory SKILL (live gateway +
  exact API version/paths marked 待核实; self-test = in-repo mock Gateway, both flavors).

### Added — BAS controller-layer integration (building edition, read-first)
- **New `bas` connector** (`iaiops/connectors/bas/`) — a config-driven HTTP reader for the vendor
  supervisory-controller REST layer that sits ABOVE the `bacnet` field-protocol connector: Johnson
  Controls **Metasys (OpenBlue) REST** and Tridium **Niagara oBIX/REST**. A small per-vendor
  **dialect** (resource paths + field aliases) folds each controller's JSON into one neutral schema;
  reuses the shared `requests` stack (no new HTTP dep) and the `make_session` lifecycle, with
  bearer/token auth resolved from the encrypted secret store by key name. Vendor names stay inside
  the connector (brand-isolation).
- **New `bas_tools`** (building EDITION module) — `bas_point_list`, `bas_point_read`, `bas_alarm_list`,
  `bas_trend_read` (all READ, low), plus `bas_command` (**WRITE, HIGH/MOC**, default-OFF, dry-run +
  double-confirm, undo captures the prior value, and a **life-safety object denylist** —
  fire/smoke/egress/pressurization points are refused outright before any network I/O).
- **`bas` extra** (`pip install iaiops[bas]`, reuses the MTConnect `requests` pin) folded into the
  `building` bundle; support-version matrix rows added to the building SKILL (live devices + native
  oBIX-XML encoding marked 待核实; self-test = in-repo mock controller).

## 0.12.0 — 2026-07-12

> **Edition build-out.** Two new industry editions (**warehouse**, **clinical**) and SKILLs for the
> previously profile-only **renewables** / **plcnext**; a **per-edition tool mechanism**
> (`EDITION_MODULES`) so an edition carries its own tools without inflating the always-on brain; a
> **downtime triage copilot** and **legacy-PLC visibility** profile; and a signature analysis tool
> for every industry edition. All read-first, cite-first, advisory.

### Added — process heat-exchanger fouling + building zone comfort
- **process `heat_exchanger_fouling`** (process_tools) — hot-side temperature effectiveness ε =
  (hot_in − hot_out)/(hot_in − cold_in) per reading, first-half vs second-half; `fouling` when the
  mean is below the floor or it declined beyond the threshold (the signature that precedes a forced
  clean). Cited by the effectiveness numbers.
- **building `zone_comfort`** (building_tools) — occupied-zone comfort + IAQ vs ASHRAE 55 / 62.1
  (temp 20–26 °C, RH 30–60 %, CO₂ ≤ 1000 ppm); per-parameter breach flags, worst-first.

### Added — renewables & plcnext editions + second edition tools (water/fab)
- **New `iaiops-renewables` edition SKILL** (the `renewables` profile had none) + signature tool
  **`pv_performance`** (new `renewables_tools`): flags underperforming PV strings by performance
  ratio vs expected (explicit / nameplate×irradiance) or the fleet median — the soiling/shading/
  failed-string signature. Worst-first, cited.
- **New `iaiops-plcnext` edition SKILL** — a packaging edition documenting PLCnext / vPLC access over
  its built-in OPC-UA (4840) + Modbus process-data server; reuses the OPC-UA/Modbus tools + brain,
  no new connector, no edition tool.
- **water `water_quality_compliance`** (water_tools) — finished-water turbidity / free-chlorine / pH
  vs drinking-water limits (overridable per permit), worst-first, the continuous-compliance companion
  to `disinfection_ct`.
- **fab `defect_pareto`** (fab_tools) — defect-category Pareto with cumulative share and the vital-few
  to the 80 % line, the quality follow-on to `spc_check`.

### Added — water / building / factory edition signature tools (via EDITION_MODULES)
Rounds out every industry edition with its own signature tool, each scoped to its edition module:
- **water `disinfection_ct`** (new `water_tools`) — SWTR disinfection credit: CT = free-chlorine
  residual × T10 contact time per contact basin vs the required CT (supplied from the utility's CT
  table); per-basin ratios worst-first. Does not embed the CT tables.
- **building `economizer_check`** (new `building_tools`) — AHU economizer FDD: simultaneous
  heat/cool, not-economizing (free cooling available but damper at minimum + mechanical cooling on),
  and economizing-when-locked-out; per-AHU faults citing the temperatures/states.
- **factory `changeover_analysis`** (new `factory_tools`) — SMED changeover durations: the gap
  between the last good part of one product and the first of the next; ranks the longest, totals the
  lost time, each cited by its bounding timestamps.

### Added — four edition-scoped signature tools (all via EDITION_MODULES)
Each rides its edition's own tool module — loaded only when that edition is selected, never the
always-on brain — the mechanism working across four verticals:
- **warehouse `sortation_health`** (`warehouse_tools`) — sorter read-rate / no-read / mis-sort
  analysis over per-divert records; ranks the worst chutes; every rate cited by counts.
- **clinical `or_environment_check`** (`clinical_tools`) — operating-room ventilation vs ASHRAE 170
  Table 7.1 (temp 20–24 °C, RH 20–60 %, ≥20 ACH); per-parameter breach flags, worst-first.
- **process `control_loop_health`** (new `process_tools`) — PID loop triage from a PV/SP/OP capture:
  oscillation (error-crossing rate), sustained offset, output saturation → worst-wins verdict.
- **fab `spc_check`** (new `fab_tools`) — SPC control-chart rules (Western Electric 1–4 + a 6-point
  Nelson trend) over a measurement series, each violation cited by point index; Cp/Cpk with spec limits.

### Added — line_bottleneck (warehouse edition tool, first EDITION_MODULES user)
- **`iaiops/core/brain/throughput.py`** + governed MCP tool **`line_bottleneck`** (in a new
  `warehouse_tools` **edition module** attached to the `warehouse` edition): Theory-of-Constraints
  over per-station throughput / cycle-time data — the slowest station is the line's constraint and
  sets the line rate; starvation/blocking corroborate (upstream blocks, downstream starves). Ranks
  the line, names the constraint + co-constraints within a %, tags each station starved/blocked,
  cites the number. Pure, read-only, advisory. Loads ONLY for `IAIOPS_MCP=warehouse` — the first
  tool to use the new per-edition mechanism instead of the always-on brain.

### Changed — per-edition tool modules + raised tool-flood threshold (architecture)
- **`EDITION_MODULES`** — a named edition can now carry its own `@mcp.tool` group beyond its
  protocols and the always-on brain. These modules load ONLY when that edition is selected (never a
  bare protocol key, never the global brain), so edition-specific tools no longer have to be
  smuggled into a protocol module or inflate the always-on surface. `selected_tool_modules` /
  `selected_editions` wire it; `selection_tool_count` and the skill-sync surface check use the same
  single source of truth.
- **`clinical_tools`** — `isolation_room_check` + `medical_gas_check` moved out of `bacnet_tools`
  into a dedicated edition module attached to the `building` and `clinical` editions. A raw
  `IAIOPS_MCP=bacnet` selection no longer pulls them (correct scoping); building/clinical still do.
- **`TOOL_FLOOD_WARN_THRESHOLD` 60 → 100** — the always-on brain (~49) plus a full edition's
  protocols + edition modules legitimately reaches ~60-85 (building ≈ 83), so 60 fired on normal
  editions. 100 sits above any single intended edition while still flagging `IAIOPS_MCP=all`
  (~140 tools) — the case the warning is meant to catch.

### Added — clinical-facility edition (医疗设施) + medical-gas safety check
- **New `clinical` profile + `skills/iaiops-clinical/SKILL.md` edition** — promotes the healthcare
  slice out of `iaiops-building` into its own vertical (hospital facilities: different buyer /
  NFPA 99 & infection-control compliance than generic building management). Protocols: BACnet
  (BMS) + Modbus (gas alarm panels / meters) + OPC-UA (SCADA); reuses the building/BACnet tools and
  brain. New `iaiops-mcp-clinical` entrypoint.
- **`medical_gas_check`** (in `clinical_facility` / `bacnet_tools`, alongside `isolation_room_check`):
  grades medical-gas / vacuum source pressures against NFPA 99 / HTM 02-01 — positive-pressure gases
  (O2 / medical air / N2O / nitrogen / CO2) must sit in ~345–380 kPa; medical vacuum / WAGD must be
  deep enough — into normal / low_pressure / high_pressure / insufficient_vacuum / critical,
  worst-first, citing the number. Pure, read-only, advisory (the station's NFPA 99 alarm panel
  remains source of truth).

### Added — warehouse / intralogistics edition (仓储/物料搬运)
- **New `warehouse` profile + `skills/iaiops-warehouse/SKILL.md` edition** for distribution
  centers / material handling: EtherNet/IP (Rockwell conveyor & sorter PLCs) + Profinet (Siemens
  lines) + Modbus (VFD/meters) + OPC-UA (WMS/WCS gateways) + MQTT-Sparkplug (AGV/AMR & IoT), plus
  the cross-protocol brain. A packaging edition — reuses `pdm_forecast` (conveyor-drive bearing/
  thermal trend), `downtime_triage`, OEE and alarm analysis as-is (no new global-brain tool).
- **Two material-handling Modbus templates** (`conveyor_vfd`, `agv_battery`) — placeholder register
  maps (待核实, vendor-specific) whose drive_temperature / motor_current / state_of_charge feed
  `pdm_forecast`. New `iaiops-mcp-warehouse` console entrypoint.

### Added — clinical-facility safety: isolation-room pressurization (building edition)
- **`iaiops/core/brain/clinical_facility.py`** + governed MCP tool **`isolation_room_check`**
  (in `bacnet_tools`, so it is scoped to the `iaiops-building` / BACnet edition — NOT the always-on
  global brain, keeping single-protocol sites under the tool-flood target): the healthcare slice
  generic BMS lacks. Grades each isolation room's differential pressure against ASHRAE 170 / CDC — airborne-
  infection isolation (AII) must stay **negative**, protective-environment (PE) **positive**, at a
  minimum ~2.5 Pa — into `reversed` (wrong polarity, a reportable patient-safety event), `breach`
  (right polarity but too weak), `low_margin`, or `compliant`, worst-first, citing the number behind
  every flag. Pure analysis over differential-pressure readings (from `bacnet_read_points` AI points
  or a historian); read-only and advisory. First step toward an `iaiops-clinical` edition if the
  hospital-facility vertical warrants its own routing identity.

### Added — legacy-PLC visibility profile (what am I inheriting?)
- **`iaiops/core/brain/plc_visibility.py`** + governed MCP tool **`plc_program_visibility`**
  (`plc_program_tools`): a maintainability/operational-risk read one level above the structural
  outline — folds a parsed EXPORTED program (SCL/ST/AWL/L5X) into documentation coverage +
  least-commented blocks, **unreferenced blocks** (possible dead code, flagged honestly — could be
  an entry/task routine or an unresolved call), **complexity hotspots**, **risky constructs**
  (unconditional JMPs, retentive RTO timers, loops), and a **transparent additive risk score**
  whose every point cites its reason. Structural only, cite-first (source_file + line / rung),
  read-only; reuses `plc_program` — no new live-PLC access.

### Added — downtime triage copilot (composes the three downtime lenses)
- **`iaiops/core/brain/downtime_copilot.py`** + governed MCP tool **`downtime_triage`**
  (`downtime_tools`, always-on brain): one call that composes **`alarm_cascade`** (which alarm to
  look at first), **`downtime_root_cause`** (the cited causal verdict), and **`pdm_forecast`** (which
  signals were degrading *before* the trip) over a single incident. Adds a **cross-check**: is the
  first-out alarm actually cited by the RCA's primary cause (`corroborated`) or does the verdict lean
  elsewhere (`diverging`)? Pure composition — every field traces to a sub-report echoed for
  drill-down; read-only, advisory, thin-evidence-honest. Answers the operator's three simultaneous
  questions on a stopped line in one shot.

### Added — alarm-cascade collapse (first-out root)
- **`alarm_cascade`** brain fn + governed MCP tool (`alarm_flood` / `alarm_tools`): collapses an
  alarm flood into cascades — a new cascade starts after a quiet gap > `window_s` — and reports each
  cascade's **first-out** alarm (earliest annunciation) as the likely root, plus downstream members
  and chattering sources. Answers "which alarm to look at first" in a 100+/10-min flood. First-out is
  a transparent, timestamp-cited heuristic (NOT causal — that's `downtime_root_cause`); read-only,
  pure over provided events, or live via the OPC-UA active-condition scan. Complements
  `alarm_flood_analysis` (the "how bad") with the "what's the root".

### Added — predictive maintenance (trend + time-to-threshold)
- **`iaiops/core/brain/pdm.py`** + governed MCP tool **`pdm_forecast`** (`pdm_tools`, always-on brain):
  the predictive step above `baseline_check` (which flags an *already-happened* violation). From a
  value's recent history it fits a robust **Theil–Sen** trend (median of pairwise slopes — no ML,
  outlier-resistant) and, if the trend continues, estimates the **ETA to the nearest warn/alarm
  limit** in the direction of travel → status `insufficient_data | stable | degrading | imminent`.
  Refuses thin history (< 30 samples); cited (window / slope / current / limit / ETA); read-only,
  pure over the provided series. Reused across renewables / warehouse / manufacturing PdM.

## 0.11.0 — 2026-07-12

> Big feature batch from the IGEL/OT field work: an **adapter belt** (InfluxDB sink · NATS egress ·
> on-box Ollama), governed **MCP tools** for it, an **HTTP/SSE transport + account/IP allowlist**
> (gateway-frontable), a **fleet / multi-site** rollup, a **renewables (solar/wind)** edition + PdM,
> a real **Margo `v1-alpha1`** app descriptor, **IGEL** submission readiness, and **GHCR** image
> publishing. Docs/packaging + additive features; no breaking API changes. (Deprecated brain aliases
> `health_summary` / `anomaly_scan` remain — now scheduled for removal in 0.12.)

### Added — adapter belt (lightweight core, open to every interface)
- **Formalized the `ingress → core → egress` architecture** (`docs/ADAPTERS.md`): the core binds no
  store/bus/host/model; every integration is an optional, lazily-imported adapter behind a tiny SPI.
- **`influxdb` historian sink** (`iaiops.core.sink.influxdb`, extra `iaiops[influxdb]`) — InfluxDB
  v1/v2 via line protocol over HTTP (reuses the `requests` pin; no heavy SDK). Registered in
  `get_sink` / `SUPPORTED_SINKS`.
- **Stream egress SPI + NATS publisher** (`iaiops.core.egress`, extra `iaiops[nats]`) — publish
  normalized points + RCA/alarm events to a bus (`publish_points` / `publish_event`). Read-first safe
  (egress of iaiops' own reads/findings, never a control write).
- **On-box local-LLM SPI + Ollama provider** (`iaiops.core.llm`, extra `iaiops[ollama]`) — fully
  air-gapped **narration of an already-cited RCA verdict**; strict cited-only prompt, never derives
  causes (`docs/RCA.md`).
- **Governed MCP tools for the belt** (always-on brain modules `egress_tools` / `llm_tools`):
  `stream_publish` / `stream_publish_event` (publish reads/findings to NATS) and `rca_narrate`
  (on-box LLM narration) — all `[READ][risk=low]`, so an agent can drive egress + narration directly.
- **`docs/RCA.md`** — explains the deterministic, cited, anti-hallucination RCA core ("not a black
  box"); **`docs/FOOTPRINT.md`** — small-by-design footprint + measurement recipe.
- All three adapters are mock-tested (no live server/model needed) and marked `待核实` against real
  backends.

### Added — renewables (solar/wind) edition + PdM
- New **`renewables`** edition (光伏/风电): `IAIOPS_MCP=renewables` / `iaiops-mcp-renewables` /
  `pip install iaiops[renewables]` (modbus + opcua + sparkplug). Device-level monitoring of **PV
  inverters** (reusing the existing SUN2000 / Growatt Modbus templates) + a new
  **`generic_wind_turbine`** template + plant SCADA, with **predictive/preventive maintenance** via
  the existing baseline + RCA brain. Solar/wind **semantic classes** added (irradiance, wind_speed,
  rotor_speed, pitch_angle, yaw_angle, state_of_charge) — placed first so they aren't shadowed by
  greedy generic hints. Grid/substation telecontrol (IEC-104/DNP3/61850) stays in `iaiops-energy`.

### Added — fleet / multi-site rollup (central view over many edge sites)
- **`iaiops/core/brain/fleet.py`** + governed MCP tools **`fleet_status`** / **`fleet_incidents`**
  (`egress`-adjacent always-on brain module `fleet_tools`): the tier above
  `data_quality_fleet_rollup` (per-endpoint, one site) — aggregate per-site status reports across a
  whole **fleet of edge sites** (health status, offline-by-staleness, worst-sites-first, fleet score)
  and roll up active RCA incidents into fleet-wide top causes. Read-only, pure over provided reports;
  a central collector gathers them via a shared historian or each site's HTTP/SSE MCP. Matches the
  IGEL-UMS "centrally manage a large fleet of edge sites" story.

### Added — HTTP/SSE MCP transport + account/IP allowlist (gateway-frontable)
- The MCP server can now run over **HTTP/SSE** instead of only stdio, so it can sit **behind a
  gateway** (e.g. a FastAPI front): `IAIOPS_MCP_TRANSPORT=stdio` (default) `| sse | streamable-http`
  (alias `http`), with `IAIOPS_MCP_HOST` / `IAIOPS_MCP_PORT` (`mcp_server/transport.py`).
- **Account/IP allowlist** (`iaiops/core/governance/allowlist.py`, env `IAIOPS_ALLOWLIST_ACCOUNTS` /
  `IAIOPS_ALLOWLIST_IPS`, CIDR-aware) — defense-in-depth for the standalone HTTP case (an ASGI
  middleware 403s non-allowlisted client IPs) and a reusable check for a fronting gateway. stdio is
  unchanged; a non-loopback bind with no allowlist logs a warning. Answers the recurring Margo/IGEL
  "stdio vs HTTP transport" question.

### Added — OCI image publishing (GHCR)
- `.github/workflows/publish-image.yml` — on a `vX.Y.Z` tag (or manual dispatch) builds + pushes the
  hardened image (`deploy/margo/Dockerfile`) **per edition profile, multi-arch (amd64/arm64)** to
  `ghcr.io/industrial-aiops/iaiops:<version>-<profile>` (factory also tagged `<version>` + `latest`).
  Installs the published PyPI wheel — publish to PyPI first, then tag. No local Docker needed. This
  unblocks IGEL Managed-Container deploys and a working IGEL-Community recipe.

### Changed — IGEL App Portal submission readiness (`deploy/igel`)
- `deploy/igel/README.md` documents the **IGEL Ready** path (private App Creator vs certified App
  Portal) + the Guided App Submission workflow (acceptance → security review → publishing) and its
  requirements. Recommends the **Managed Container (OCI)** route to sidestep the debian/ubuntu-only
  dependency constraint (a pip/Python app is awkward as a native recipe).
- `app-recipe/`: `app.json` bumped to 0.10.1 with the `public_version`-absent submission rule; added
  `igel/thirdparty.json` (binary manifest). Version refs across `deploy/` aligned to 0.10.1.

### Changed — Margo app descriptor rebuilt to the real spec
- `deploy/margo/margo-application.yaml` → **`deploy/margo/margo.yaml`** (spec-canonical filename),
  rewritten to the actual **`margo.org/v1-alpha1` ApplicationDescription** schema (docs.margo.org,
  PR1 pre-draft): real `deploymentProfiles` (compose) / `components` / `requiredResources` /
  `parameters` (env-var targets) / `configuration` + validation `schema`. The `待核实` markers now
  cover only genuine gaps — the hosted+signed package location/key, and the missing secret-parameter
  flag (our open app-package-definition-wg question). Still not conformance-tested → not compliant.

## 0.10.1 — 2026-07-10

> Docs + packaging only — **no functional/source code change** vs 0.10.0 (hence a patch).
> Also folds in doc refreshes: FINS CLI examples, READMEs to 0.10.0 (14 protocols / 132 tools).

### Added — edge-native / Margo ecosystem alignment (docs + packaging skeleton)
- **`docs/MARGO-ALIGNMENT.md`** — positions iaiops as a [Margo](https://margo.org/) **edge
  application** (device / orchestration / application role map), with an honest gap analysis, a
  contributor-first participation plan, verified join steps, and ready-to-paste WG posts.
- **`deploy/margo/`** — container + application-description **skeleton**: `Dockerfile` (non-root,
  read-only-rootfs friendly, headless `iaiops-mcp`, build-arg `PROFILE`), `compose.yaml` (hardened:
  `cap_drop: ALL`, no-new-privileges, no inbound ports, single state volume), `margo-application.yaml`
  (app-description skeleton — every unconfirmed field marked `待核实`), and a README.
- **`deploy/igel/`** — IGEL OS 12 **distribution overlay** (one candidate host; core image stays the
  neutral `deploy/margo/` one): Managed-Container route (reuse the OCI image) + an `igelpkg`
  app-recipe skeleton (`app.json` / `igel/install.sh` / systemd unit), all IGEL-specific specifics
  marked `待核实`. IGEL is referenced ONLY inside this overlay (brand-isolation rule).
- **Positioning** — README (EN + zh-CN) gain an *edge-native / Margo* deployment subsection;
  `pyproject.toml` keywords add `edge` / `iiot` / `edge-computing` / `margo` / `edge-interoperability`;
  `docs/ROADMAP.md` gains an "Ecosystem / edge packaging (Margo)" section.
- **Honesty note:** iaiops is **NOT Margo-compliant** yet — a built/pushed image, a real app-package
  descriptor, and a passing conformance-toolkit result are all roadmap `⏳`. No material claims
  compliance until that published result exists.

## 0.10.0 — 2026-07-02

### Changed — session factory refactor (B1)
- `iaiops/core/runtime/connection.py` (982 lines) refactored: the shared guard → build →
  connect/translate → yield → teardown-swallow lifecycle is now a single generic
  `make_session()` factory in `iaiops/core/runtime/session_factory.py` (exported from
  `iaiops.core.runtime` for downstream packages, e.g. iaiops-energy); each protocol's
  `_build_*`/`_translate_*` moved into its connector (`iaiops/connectors/<proto>/transport.py`),
  with `connection.py` reduced to a thin assembly module keeping the exact same public API,
  semantics, and test monkeypatch points (`connection._build_<proto>_*`). Zero behavior change.
### Added — conservative baseline learning (A6)
- **Change-log baseline — explicitly NOT black-box anomaly detection** (MARKET-INSIGHTS R6:
  zero false positives or it is noise). New brain modules `iaiops.core.brain.baseline`
  (pure: robust p1/p99 + median/MAD band, no ML deps) and `baseline_store`
  (`~/.iaiops/baselines.json`, owner-only 0600, atomic writes).
- Learning **refuses thin history** (< 100 usable samples or < 24h span) with an explicit
  `insufficient_data` verdict listing exactly what is missing; operator changes recorded via
  the change log restart learning at the latest change point (the band never mixes regimes).
- Checking is **silent by default**: violations only beyond p1/p99 by > 3×MAD AND sustained
  ≥ 3 consecutive samples (single spikes never flagged); every violation cites the baseline
  window (from/to ts, n samples), the band values, and the offending samples' ts/values.
- New governed MCP tools (all `[READ][risk=low]`, always exposed with the brain):
  `baseline_learn` / `baseline_check` / `baseline_record_change` / `baseline_status`
  (`no_baseline` / `learning` / `ok` / `violation` — never guesses; bounded outputs).
- New CLI: `iaiops baseline learn|check|change|status` over the local SQLite history.
### Added — historian read integration (A7)
- **Historian readers** (`iaiops/core/sink/reader.py`): a `HistorianReader` protocol +
  `get_reader()` registry mirroring `get_sink()`, with `sqlite` (delegates to the existing
  local query layer), `tdengine`, and `iotdb` readers querying the SAME layout their sinks
  write. Same lazy optional extras as the sinks (`iaiops[tdengine]` / `iaiops[iotdb]`) with
  teaching errors; validated ISO time bounds, capped limits, parameterized/neutralized queries.
- **RCA pre-incident evidence**: an optional per-site `historian:` config block
  (`reader: sqlite|tdengine|iotdb`, password via the encrypted secret store) lets
  `downtime_root_cause` / `downtime_root_cause_live` pull the 2h pre-incident window
  (`iaiops/core/brain/rca_history.py`) and score tag trends as one more evidence class —
  citations name the source (`historian:<name>`), window, and sample count. Strictly
  additive: without the config, RCA output is byte-identical (test-proven).
- **Governed MCP tools** (always-on brain module `historian_tools`): `historian_query`
  (bounded rows + truncation flag) and `historian_coverage` (per-tag row counts +
  first/last timestamps — "what history do we actually have"), both `[READ][risk=low]`.
- **CLI**: `iaiops historian query` / `iaiops historian coverage` alongside the existing
  `historian push`.
- Edition skills (fab/factory/process/building/water) document the two new brain tools.
### Added — legacy PLC program explainer (A8)
- New brain package `iaiops/core/brain/plc_program/`: structural extraction over
  **exported** program text files (Siemens SCL/ST `.scl`/`.st`, AWL/STL `.awl`,
  Rockwell Studio 5000 `.L5X`) — never a live PLC upload. Every extracted element
  carries `source_file` + `line` (rung number for L5X ladder) so the explaining
  agent must cite real locations. L5X is parsed with stdlib `xml.etree` plus a
  pre-parse DTD/entity rejection (XXE hardening); malformed/truncated files
  degrade to `parse_errors` entries instead of crashing.
- 3 governed READ tools (always-on brain module `plc_program_tools`):
  `plc_program_outline` (blocks / VAR sections / IF-CASE branches /
  timers-counters / call graph, bounded with truncation flags),
  `plc_program_xref` (every read/write/call/declare site of a symbol or absolute
  address with the source line quoted), `plc_program_section` (one named block's
  source text, ≤200 lines). Path validation: file must exist, ≤5 MB,
  extension allowlist, no directory walking.
- CLI: `iaiops program outline|xref|section`.
- All 5 edition skills document the 3 tools under 跨协议脑.
### Changed — explicit tool menu by default + brain-only server (B2/B3) **BREAKING**
- **No default tool selection**: a bare `iaiops-mcp` (no `IAIOPS_MCP` env) no longer
  silently exposes the full 100+ tool surface — it prints the selection menu (named
  profiles + protocol keys + per-selection tool counts + examples) to stderr and exits 2.
  `IAIOPS_MCP=menu` prints the same menu explicitly; `IAIOPS_MCP=all` still works as an
  explicit power-user opt-in (a tool-flood warning is logged above 60 tools).
- **Brain-only server (B3)**: new named selection `IAIOPS_MCP=brain` (cross-protocol
  brain, zero protocols) + `iaiops-mcp-brain` console script; new `IAIOPS_MCP_NO_BRAIN=1`
  toggle registers protocol selections *without* the brain modules, so multi-process
  sites run 1 brain MCP + N brain-less protocol MCPs with no duplicate tool names.
  The `protocols_supported` discovery tool stays exposed even under NO_BRAIN.
- **Migration**: set `IAIOPS_MCP=<selection>` (comma list of protocols and/or a named
  profile) or launch a pre-scoped `iaiops-mcp-<name>` entrypoint; to restore the old
  behavior exactly, set `IAIOPS_MCP=all` explicitly.

### Added — Omron FINS connector (A5)
- **Omron FINS** (backlog A5, APAC/华南 install base): new `fins` protocol —
  in-repo **stdlib-only** FINS client (`iaiops/connectors/fins/client.py`, no
  third-party dependency): 10-byte FINS header framing, FINS/UDP (default port
  9600) + FINS/TCP (node-address handshake per W342), SID matching (mismatch
  rejected, retries=0), bounded response parsing, end-code table per Omron
  W227/W342. Commands: 0101 memory-area read (words/bits, DM/CIO/W/H/A/EM),
  0102 memory-area write, 0501 controller data read, 0601 controller status.
- MCP tools `fins_cpu_info` / `fins_cpu_status` / `fins_read_words` /
  `fins_read_bits` / `fins_read_many` [READ, risk=low] + `fins_write_words`
  [WRITE, risk=HIGH, MOC: dry-run default, BEFORE-value capture, undo
  descriptor]; CLI `iaiops fins cpu|status|words|bits|write-words`
  (double-confirm on `--apply`); `fins_session` via the B1 session factory;
  `IAIOPS_MCP=fins` menu entry + `iaiops-mcp-fins` entrypoint; added to the
  `factory` profile/extra (`fins = []` extra — stdlib, pins nothing).
- Self-test: in-repo mock FINS UDP/TCP responder (tests/test_fins.py). Live
  Omron PLC behaviour and banked-EM access remain 待核实.

### Added — IO-Link connector (A10)
- **IO-Link connector** (`iaiops/connectors/iolink/`, read-only v1): sensor-level visibility via
  the IO-Link master's HTTP/JSON interface (IO-Link consortium "JSON Integration"). Both dialects
  selectable per endpoint via `flavor:` — `iotcore` (ifm IoT-Core POST envelope, default) and
  `rest` (plain-REST GET, Balluff/Turck-style). Reads: master identity (`/deviceinfo/...`),
  bounded ≤32-port sweep (mode/status + connected-device identity), per-port device identity,
  process-data-in (raw hex + byte array), ISDU acyclic parameter read (`iolreadacyclic`). NO
  write tools. Bounded/size-capped HTTP (response cap 256 KiB, timeout from `timeout_s`), JSON
  schema-checked with teaching errors. Reuses the MTConnect HTTP pin (`iaiops[iolink]` →
  `requests`); no new hard deps.
- 6 governed MCP tools (all [READ][risk=low]): `iolink_master_info`, `iolink_ports`,
  `iolink_device_info`, `iolink_read_pdin`, `iolink_read_isdu`, `iolink_scan`; registered in the
  `factory` and `building` profiles + `iaiops-mcp-iolink` entrypoint; CLI `iaiops iolink
  master|ports|device|pdin|isdu|scan`; doctor probe + init wizard support.
- Self-test: in-process mock IO-Link master (both flavors) in `tests/test_iolink.py`
  (identity/ports/pdin/isdu round-trips, size cap, malformed JSON, flavor switching,
  governance markers). Live master datapoint paths 待核实.
### Changed — brain/opcua tool split, flagship function refactor, tool-signature polish (B4/B5/B7)
- **B4 — DEPRECATED: `health_summary` / `anomaly_scan`** are OPC-UA-specific and moved out of
  the always-on brain into the opcua protocol module as **`opcua_health_summary` /
  `opcua_anomaly_scan`**. The old names remain registered in the brain for ONE release as
  deprecated aliases: they delegate to the same implementation and their response gains
  `"deprecated": "renamed to opcua_health_summary; this alias is removed in 0.11"`
  (respectively `opcua_anomaly_scan`). **Both aliases are removed in 0.11** — switch to the
  `opcua_*` names. Edition skills updated (new names in the OPC-UA section; old names marked
  deprecated in the 跨协议脑 line).
- **B5 — flagship brain function split (pure refactor, zero behavior change)**:
  `diagnostics.py` `subscription_health` / `diagnose_dataflow` and `rca.py` `downtime_rca` /
  `_score_alarms` decomposed into `_collect_*` / `_score_*` / `_render_*` helpers so each
  public function is <50 lines of orchestration; worst nesting in
  `iaiops/core/governance/patterns.py` (`PatternEngine._load` / `match`) flattened via
  early-continues and an extracted `_evaluate_armable`.
- **B7 — tool-signature polish**: all MCP tool parameters now use parameterized generics
  (`list[str]`, `dict[str, float]`, … — no bare `list`/`dict`, so the LLM-facing JSON schema
  carries element types); docstring risk tags unified — every read tool's first line starts
  `[READ][risk=low]`, writes keep `[WRITE][risk=HIGH][MOC]`. Enforced by the new
  `tests/test_tool_annotations.py` walking every registered tool.

## 0.9.0 — 2026-07-02

### Security — governance hardening (from full audit)
- **Approver gate now enforced out-of-the-box**: with no `risk_tiers` in `~/.iaiops/rules.yaml`,
  high/critical risk operations default to tier `dual` (approver required, rule `builtin_default`)
  instead of tier `none`. `iaiops init` writes a commented starter `rules.yaml` with an explicit
  `risk_tiers` gate. Dead `risk_requires_confirmation()` removed.
- **Policy engine fails closed**: a malformed or deleted `rules.yaml` now retains the
  last-known-good rule set (audited as `policy_load_failed`) instead of silently reverting
  to allow-all.
- **Policy kill switch constrained**: renamed to `IAIOPS_POLICY_DISABLED` (legacy
  `OPCUA_POLICY_DISABLED` still works with a deprecation warning) and it never bypasses
  high/critical risk checks.
- **One-shot approval tokens**: `iaiops approve <tool> --endpoint <ep> --by <name> [--ttl]`
  writes a single-use, TTL-bound approval consumed by the next matching governed call
  (`approver_source="token"` in audit). The static `OPCUA_AUDIT_APPROVED_BY` env var remains
  as a deprecated fallback (`approver_source="env"`, once-per-process warning).
- **Audit fails closed for writes**: high/critical operations are denied (`audit_unavailable`)
  when the audit row cannot be written; low/medium proceed with a warning.
- **Audit tamper-evidence**: SHA-256 hash chain (`prev_hash`/`row_hash`) on every audit row +
  `iaiops audit verify` to walk the chain and report the first broken link.
- **SIEM forwarding hardened**: bare hosts default to `https://`, loud warnings on plaintext
  sinks, optional `Authorization: Bearer` via `IAIOPS_FORWARD_TOKEN`.
- **Startup governance assertion**: the MCP server refuses to start if any registered tool
  lacks `_is_governed_tool`.
- **Plaintext secret remnants removed**: `.env.migrated` is rewritten with secret values
  stripped after migration; `iaiops doctor` reports an ERROR while a plaintext `.env` is in
  use and warns when an OPC-UA target pairs `username` with `security_mode: None`.

### Fixed
- **Connect timeouts**: new `TargetConfig.timeout_s` (default 10 s, `IAIOPS_TIMEOUT_S` fleet
  override) threaded into the OPC-UA / S7 / MC / EtherNet-IP builders so an unroutable host
  no longer blocks a tool call for the OS TCP timeout.
- **SKILL.md brought back in sync with the code**: write-tool count corrected (8, not 6),
  `profinet_dcp_set` and `bacnet_write_property` documented as MOC-gated high-risk writes
  (the skill previously claimed they didn't exist), ~23 missing tools added incl. a HART-IP
  section, energy-protocol triggers now redirect to `iaiops-energy`. A new
  `tests/test_skill_sync.py` gate keeps skill and registered tools from drifting again.
- `server.json`: title corrected to "Industrial-AIOps", `environmentVariables` declared
  (`IAIOPS_MCP`, `IAIOPS_CONFIG`, `IAIOPS_MASTER_PASSWORD`).

### Added — queryability layer (A2)
- **Local SQLite sink** (`historian_push(sink="sqlite")` / `iaiops historian push --sink
  sqlite`): normalized samples land in a queryable on-box store `~/.iaiops/data.db`
  (WAL, 0600/0700 hardening, `samples(ts, endpoint, protocol, tag, value, quality, unit)`
  + indexes); keeps non-numeric values as text (the TSDB sinks stay numeric-only).
- **`iaiops export csv|sqlite|parquet`** — open-format export FROM the local store with
  `--since/--until/--endpoint/--tag/--limit` filters (fail-fast validation). CSV/SQLite
  are stdlib-only; Parquet via the new optional extra `iaiops[export]` (pyarrow, lazy
  import with a teaching error). Governed MCP counterpart: `export_data` ([READ][risk=low],
  bounded ≤200-row inline preview, returns path + row count).
- **Prometheus/Grafana bridge** — `iaiops metrics serve --port 9184` exposes `/metrics`
  (text format 0.0.4, stdlib http.server): `iaiops_tag_value{endpoint,protocol,tag,unit}`
  gauges (latest value per tag) + `iaiops_samples_written_total` /
  `iaiops_audit_events_total` / `iaiops_tool_errors_total` counters. Binds 127.0.0.1 by
  default; explicit `--host 0.0.0.0` warns loudly. Recipe: `docs/GRAFANA.md`.
### Added — compliance report generation (A3)
- **`iaiops compliance report --out report.md [--html] [--site NAME] [--level l2|l3]`**:
  renders the existing compliance crosswalk into a deliverable document — title-page
  metadata (site / date / iaiops version), per-pillar 等保 2.0 L2/L3 status table,
  IEC 62443 FR1–6 crosswalk, honest gap list, and a governance-controls appendix
  (audit hash chain / approval tokens / dry-run+undo / mTLS). Markdown by default,
  `--html` via a stdlib converter (no new deps). Onboarding aid, 非认证.
- **`iaiops compliance evidence --out bundle.zip [--since ISO] [--until ISO]`**:
  audit-evidence zip with deterministic member names — `audit_rows.jsonl` (secrets
  already redacted upstream), `chain_verification.json` (hash-chain walk),
  `rules.yaml` (if present), `doctor_summary.json`, `manifest.json`. Output paths
  reject `..` traversal; parent dirs created 0700, bundle written 0600.
- New governed MCP tools `compliance_report` (inline markdown capped at ~400 lines,
  else write to `out_path`) and `compliance_evidence_bundle`, both [READ][risk=low].
### Added — ISA-18.2 alarm flood analysis (A4)
- **New brain module `iaiops.core.brain.alarm_flood`** (pure, no I/O): `detect_floods`
  (flood *episodes* — start/end/count/peak rate/top contributors, per ISA-18.2's
  ≥10 alarms/10 min per operator), `chattering_alarms` (ACTIVE↔CLEARED cycle counting),
  `stale_standing_alarms` (continuously active > 24 h), `flood_summary`
  (percent-time-in-flood + avg/peak rate vs the ~1-2 alarms/10 min target, honest
  `insufficient_data` handling), and `rationalization_worksheet` (CSV-exportable rows).
- **New governed MCP tools** (`alarm_flood_analysis`, `alarm_rationalization_worksheet`,
  both `[READ][risk=low]`, bounded output with truncation flags): analyze injected events
  or collect live via the same OPC-UA active-condition scan the RCA copilot uses
  (`rca_collect.collect_active_alarms`, polled over `duration_s`).
- **New CLI commands**: `iaiops diag alarm-flood` and `iaiops diag alarm-worksheet`
  (JSON events in; deep report out, or a CSV worksheet via `--out`).
### Added — water treatment edition (A9)
- **`water` profile** (水处理): `IAIOPS_MCP=water` exposes exactly modbus + opcua + hart
  (+ the always-on brain), with a matching `iaiops-mcp-water` console script and an
  `iaiops[water]` extra that references the per-protocol extras (no duplicated pins).
- **Water-domain semantics**: the tag classifier gains dissolved_oxygen (DO/溶解氧),
  orp (氧化还原/redox), chlorine (余氯/总氯), ammonia (氨氮/NH3), suspended_solids
  (TSS/MLSS/悬浮物), membrane_pressure (TMP/跨膜压差), uv_intensity (紫外), dosing
  (加药) and aeration (曝气/风机/blower) classes, plus 流量/液位 hints on flow/level.
  Ambiguous bare tokens (do/tmp/orp) stay underscore-/context-guarded — honest `other`
  over a confident-but-wrong class.
- **Water-industry Modbus register templates**: `eh_promag_flowmeter` (E+H Promag
  process values), `hach_sc_controller` (pH/DO/turbidity sensor slots) and
  `generic_dosing_pump` (加药泵 block). All three ship with explicit 待核实 caveats and
  placeholder offsets where no fixed public vendor map exists — no invented "verified"
  addresses.
- New `tests/test_water_edition.py` pins the profile/entrypoint/extra contract, the
  water tag classes and the template catalog.

## 0.8.0 — 2026-07-02

### Changed — energy edition split out
- **The energy edition (变电/电力: IEC-104 / DNP3 / IEC-61850) moved to its own
  package**, [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)
  (`pip install iaiops-energy`), which depends on `iaiops` for the shared core (governance
  / brain / runtime / normalized model) and MCP server. Removed from this repo: the three
  connectors + their session builders (`connection.py`), MCP tool modules, CLI apps, the
  `energy` MCP profile + `iaiops-mcp-energy` entrypoint + `iaiops[iec104|dnp3|iec61850|energy]`
  extras, and `common_address`/`master_address` on `TargetConfig`. Base is now **12 field
  protocols**. See `docs/ENERGY-SPINOUT.md`. Building edition + the rest are unchanged.

### Added — Phoenix Contact PLCnext vPLC (虚拟化 PLC)
- **Route-verified** over the existing OPC-UA + Modbus connectors (no new driver): a
  dedicated `plcnext` MCP profile (`IAIOPS_MCP=plcnext`, `iaiops-mcp-plcnext`, `iaiops[plcnext]`),
  a `phoenix_plcnext_process_be` Modbus register template, and `tests/test_plcnext_route.py`
  (real in-process asyncua `Arp.Plc.Eclr` server + faked Modbus). Live PLCnext read stays 待核实.

### Added — compliance crosswalk
- **Compliance mapping expanded** with a 等保 2.0 (GB/T 22239) + IEC 62443 (FR1–6)
  crosswalk: new governed `compliance_frameworks` MCP tool + `iaiops compliance --frameworks`
  CLI; each control now carries a `crosswalk`. See `docs/CHINA.md §5.1`.
- **等保 2.0 per-level deltas** — new governed `compliance_dengbao_levels` MCP tool +
  `iaiops compliance --dengbao-level <l2|l3|二级|三级>` CLI show, per pillar, the 二级
  baseline vs the 三级 增量 and how far iaiops moves you toward it (honest status/gap
  reused from `CONTROLS`). Onboarding aid, not a certification.

### Added — connector depth
- **HART `hart_burst_sample`** (governed, read-only, risk=low) — actively samples the
  periodically-published (burst) variables (command 3) N times over one session; a
  true unsolicited HART-IP burst subscription stays 待核实.
- **Modbus vendor register templates** — added `carlo_gavazzi_em24` (scaled int32,
  CDAB), `huawei_sun2000_inverter` and `growatt_inverter` (int32/uint32/uint16 with
  scaling); each carries a `待核实` caveat and a base-relative span within the 125-reg
  read limit.

### Added — protocols
- **HART-IP TCP transport** — the HART connector now speaks HART-IP over **TCP**
  (port 5094) in addition to UDP. An endpoint selects it with `transport: tcp`
  (UDP stays the default); `_build_hart_ip_client` picks the new
  `HartIpTcpSession` vs the existing UDP `HartIpSession`. Both reuse the same
  transport-agnostic 8-byte framing (`frame_message`/`parse_message`) and the same
  session-initiate → token-passing → close sequence. The TCP session correctly
  **length-delimits** the byte stream — it reads the 8-byte header, parses
  `byte_count`, then reads exactly `byte_count - 8` more bytes (never trusting a
  single `recv` to return a whole frame). Config gained a per-protocol transport
  resolver (`_hart_transport`: `tcp` only when explicit, else `udp`); the shared
  `TargetConfig.transport` default is now `""` ("protocol default": Modbus→tcp,
  HART→udp). **Loopback-verified**: an in-process HART-IP TCP server thread
  round-trips a real HART long-frame ACK through the REAL ops/codec path to the
  primary variable. Live-gateway behaviour stays 待核实; write/device-specific
  commands remain unexposed.

### Added — RCA intelligence
- **RCA learned / configurable per-site cause weights** — the downtime
  root-cause copilot (`iaiops/core/brain/rca.py`, `downtime_rca`) gains an
  optional `cause_weights` `{cause: multiplier}` override that scales each
  cause's evidence (1.0 = neutral, today's shipped behaviour) before the noisy-OR,
  so a site can up-/down-weight causes its own history has shown to be more/less
  reliable. Overrides are validated + clamped at the boundary (unknown causes /
  non-numeric weights teach an error). New pure module
  `iaiops/core/brain/rca_weights.py` (`learn_cause_weights`) derives that profile
  from a labeled incident corpus (`[{cause, signals}]`) with a simple, explainable
  estimator — smoothed signal→cause precision relative to chance — plus anti-overfit
  guards (Laplace smoothing, a per-cause min-sample guard, and a fall-back to the
  shipped defaults when history is thin) and a human-readable rationale. Wired as a
  new MCP brain tool `learn_cause_weights` (`@governed_tool(risk_level="low")`), a
  `cause_weights` arg on `downtime_root_cause`, and CLI
  `iaiops diag learn-weights --input incidents.json` + `iaiops diag rca --weights
  profile.json`. Pure/deterministic and advisory only — it tunes ranking, never
  executes anything.

### Added — building edition (BACnet)
- **BACnet bounded COV subscriptions + read-only trend-log reads** — two new
  read-only tools on the BACnet connector (`iaiops/connectors/bacnet/ops.py`):
  - `bacnet_cov_subscribe` — a BOUNDED change-of-value capture: subscribes to one
    object's COV (`BAC0.lite.cov`), collects up to `max_notifications` OR until
    `timeout_s` (whichever first), then ALWAYS unsubscribes (`cancel_cov` in a
    `finally`). Hard-capped by both count and wall-clock — never an open
    subscription. Reports `terminated_reason` (`max_notifications`|`timeout`).
  - `bacnet_read_trend_log` — reads a device's BACnet `TrendLog` object's buffered
    log records via a single bounded `readRange` (RangeByPosition; `newest_first`
    reverses the search), normalizing each record to `{timestamp, value}`.
  - Both exposed as governed MCP tools (`@governed_tool(risk_level="low")`) and CLI
    `iaiops bacnet cov` / `iaiops bacnet trend`; added to the overview catalog.
  - The BAC0 `cov` / `cancel_cov` / `readRange` surface is VERIFIED against the
    installed BAC0/bacpypes3 (contract tests `test_bacnet_bac0_surface` +
    `test_bacnet_bac0_cov_signature`); live HVAC COV/trend behaviour stays 待核实
    (no gear). Unit-tested against a mocked network, incl. the bounded-termination
    guarantee and the always-unsubscribe invariant.

### Added — tag intelligence
- **Adopted alias-map persistence + cross-run diff** — `iaiops/core/brain/alias_store.py`
  + MCP tools `adopt_alias_map` / `diff_alias_map` + `iaiops analytics` CLI. Persists the
  adopted canonical alias map per site (JSON under `~/.iaiops/aliases/<site>.json`, dirs
  created with safe perms) and `diff_alias_map` reports **added / removed / renamed**
  (same ref, new alias) / **reclassified** (same ref, new class) tags between the stored
  map and a fresh discovery / cross-protocol asset-model run → a stable/changed verdict.
  Pure + bounded file I/O (validated at the boundary).
- **Extended semantic classifier** — `_CLASS_HINTS` in `iaiops/core/brain/semantics.py`
  gains humidity / conductivity / pH / turbidity / density (+ more unit/synonym hints) so
  fewer real tags fall to `other`. Existing classifications are unchanged (ordering rules
  intact; the OPC-UA discovery + asset-model classifier tests pass unmodified).

### Added — CI / DX
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — runs the release quality
  gate on push to `main` and on every pull request. A `gate` job (Python 3.11 +
  3.12 matrix, `uv sync --extra all`) runs `pytest -q`, `ruff check .`, and
  `bandit -q -r iaiops mcp_server` (must stay 0 Medium+). A second
  `integration-contracts` job (linux, 3.12) installs the pure-python energy/TSDB/
  HART extras that ship linux wheels (`c104`, `pyiec61850` `--pre`, `apache-iotdb`,
  `taospy`, `BAC0`, `hart-protocol`) and runs the `integration`-marked library-API
  contract tests, so the `importorskip`-gated bindings actually execute on linux.
  Hardware/root-only protocols (EtherCAT/PROFINET raw L2 sockets, live serial,
  native-build `pydnp3`) self-skip — documented inline in the workflow.

### Added — cross-protocol intelligence
- **Cross-protocol semantic / asset / alias layer** — new pure brain module
  `iaiops/core/brain/asset_model.py` (`cross_protocol_asset_model`), MCP brain
  tool `cross_protocol_asset_model` (`@governed_tool(risk_level="low")`) and CLI
  `iaiops analytics asset-model --input feeds.json --site <site>`. Fuses
  per-protocol tag *feeds* (OPC-UA `opcua_discover_tags` descriptors + Modbus
  `modbus_apply_template` tags, or any normalized tags) into ONE unified
  asset/tag model: tags are grouped into assets **across** protocols (a `Line1`
  OPC-UA folder + a `Line1` Modbus block become one asset), each is given a
  canonical cross-protocol alias `<site>.<asset>.<class_or_name>`, and a
  cross-protocol naming-quality view reports **alias collisions**, the **same
  physical quantity exposed by two protocols** (`cross_protocol_overlaps`), and
  **cryptic names**. Pure (inputs are tag dicts) and advisory only — aliases are
  SUGGESTIONS, never a server-side rename (OT-dangerous).

### Changed — shared semantics (no behaviour change)
- Lifted the tag **semantic classifier** (`classify_tag`) and **alias scheme**
  (`suggest_alias` / `alias_segment`) out of `iaiops/connectors/opcua/discovery.py`
  into a shared home `iaiops/core/brain/semantics.py`. `opcua/discovery`
  re-exports them so its public API is unchanged, and the cross-protocol layer
  imports the SAME functions — one taxonomy, no divergent fork. Existing OPC-UA
  discovery tests pass unchanged.

### Added — UNS governance (live MQTT/Sparkplug subscription)
- **Live UNS governance bridge** — closes the loop on UNS governance: until now
  `uns_topic_audit` / `uns_schema_drift` only analyzed data the caller *provided*
  (a topic list, two NBIRTH snapshots). New `iaiops/connectors/sparkplug/live.py`
  captures those inputs from a LIVE broker over a BOUNDED window (the same
  `ops._collect` collector — up to `max_msgs` messages OR `duration_s`, whichever
  first; never an open-ended loop) and feeds them straight into the analyzers:
  - `uns_live_audit(endpoint, topic, duration_s, max_msgs, …)` — captures the live
    topic tree then runs the naming-conformance + topic-sprawl audit; returns the
    audit plus a `capture` block (observed_messages / unique_topics / topics).
  - `sparkplug_live_schema(endpoint, topic, duration_s, max_msgs)` — captures
    NBIRTH/DBIRTH and builds the drift-ready `{node:{metric:datatype}}` dict
    (node = group/edge[/device]) that `uns_schema_drift` accepts.
  - `uns_live_drift(baseline, endpoint, …)` — captures the live schema and diffs it
    against a provided baseline (none/additive/breaking).
  All three are governed MCP tools (`@governed_tool(risk_level="low")`), exposed on
  the CLI as `iaiops mqtt uns-live-audit` / `live-schema` / `uns-live-drift`, and
  added to the `mqtt` protocol's overview catalog.
- **paho 2.x verified** — the bounded collector runs through paho-mqtt 2.1.0's
  `CallbackAPIVersion.VERSION2` callback surface (already used by the connection
  layer). Unit tests INJECT messages through the assigned `on_message` callback and
  assert the capture terminates on BOTH the message cap and the timeout (no live
  broker needed). One opt-in `integration`-marked end-to-end test publishes to and
  captures from a real broker — 待核实: validated locally against eclipse-mosquitto,
  skipped in CI (no broker) and not validated against a production Sparkplug host.

## 0.7.0 — HART-IP, tag discovery, data-quality & Modbus depth (2026-06-30)

New read-only **HART-IP** process-instrumentation connector, **OPC-UA tag
auto-discovery + semantic modeling**, data-quality watchdog enhancements,
Modbus byte-order auto-detect / vendor templates / RTU serial, and per-protocol
named MCP entry points — plus a live binding-validation pass that fixed three
real defects mocks never caught (see the 0.6.0 validation notes below). All
read-first; previews carry honest `待核实` caveats.

### Added — packaging / DX
- **Per-protocol & per-edition named MCP entry points** — convenience console
  scripts `iaiops-mcp-opcua`, `iaiops-mcp-modbus`, … (one per protocol) plus
  `iaiops-mcp-fab` / `-factory` / `-process` / `-energy` / `-building` (named
  profiles). Each is a thin shim (`mcp_server/entrypoints.py`) that injects the
  equivalent `IAIOPS_MCP=<name>` selection then starts the **same** server via
  `server.main` — no server logic duplicated. The shim set is generated
  data-driven from `PROTOCOL_MODULES` + `NAMED_PROFILES`, so it can't drift from
  the menu, and produces an identical registered tool set to `IAIOPS_MCP=<name>`.
  Pure sugar — the `IAIOPS_MCP` env var already delivered the capability.

### Added — Modbus connector
- **Modbus byte-order auto-detect + vendor register templates** (R4 community pain) —
  `modbus_detect_byte_order` (PURE decode logic, no device): decodes a raw register
  block under every candidate word/byte order for a numeric type (uint16/int16/
  uint32/int32/float32 → AB/BA and ABCD/DCBA/BADC/CDAB) and scores them against a
  known `hint` value and/or a plausible `[value_min, value_max]` band, returning the
  best order + confidence. Plus `modbus_list_templates` / `modbus_apply_template`: a
  curated set of vendor register maps (generic big-endian / word-swapped float blocks,
  Eastron SDM630 energy meter, Schneider PM5xxx power meter) that decode a block into
  named engineering tags. New modules `iaiops/connectors/modbus/byteorder.py` +
  `templates.py`. Fully unit-tested.
- **Modbus-RTU (serial) transport** — the Modbus connector now speaks Modbus-RTU over
  a serial line as well as Modbus-TCP. Endpoints set `transport: rtu` (or just a
  `serial_port:`) with `baudrate` / `parity` / `stopbits` / `bytesize`; the connection
  layer builds pymodbus's `ModbusSerialClient` and the same read ops (holding / input /
  coils / discrete) work unchanged. Client construction + config plumbing are
  unit-verified (monkeypatched pymodbus client). **待核实:** the live-serial round-trip
  needs real RS-485/USB hardware and is not CI-verifiable.

### Added — verticals & protocols
- **HART-IP connector (read-only, process edition)** — `hart_device_identity` /
  `hart_primary_variable` / `hart_dynamic_variables` MCP tools + `iaiops hart` CLI
  (`iaiops/connectors/hart/`), over HART-IP (UDP 5094) via the `hart` extra
  (`hart-protocol`); added to the `process` profile/bundle. The HART command codec
  (build/parse) is **verified offline** against the real library; the **HART-IP wire
  transport is 待核实** (not validated against a live HART-IP server/gateway). Write
  and device-specific commands are intentionally NOT exposed (OT-dangerous on live
  instrumentation).

### Added — intelligence layer
- **Data-quality watchdog enhancements** (`iaiops/core/brain/dataquality.py`) — extends
  the data-trust scorecard with: (1) **configurable staleness/gap per tag and per feed**
  (`staleness_s` / `gap_threshold_s`, with a feed-level `staleness_s` default) so a slow
  daily counter is not judged like a 1Hz sensor, plus `flatline_after_s` to flag a stuck
  value by its longest stall; (2) **flatline / dead-heartbeat as a first-class scored
  `liveness` section** in the scorecard output (no longer buried in per-tag flags),
  reusing `_longest_stall`; (3) **cross-endpoint fleet rollup** — new
  `data_quality_fleet_rollup` brain fn + MCP tool + `iaiops diag dataquality-fleet` CLI
  that ranks endpoints by their single worst tag and aggregates bad-quality tag counts
  across every endpoint (extends the per-endpoint `_rollup_endpoint`). Pure analysis.
- **OPC-UA tag auto-discovery + semantic modeling** — `opcua_discover_tags` MCP tool
  + `iaiops opcua discover` CLI (`iaiops/connectors/opcua/discovery.py`): walks the
  address space, collects every Variable node enriched with datatype / value /
  engineering-unit, infers a heuristic semantic class (temperature / pressure / flow /
  setpoint / alarm / state / …), groups tags into assets by browse path, and proposes
  a clean canonical alias per tag with a naming-quality report (alias collisions /
  cryptic names). Advisory + read-only — no server-side rename. Skips OPC-UA ns=0
  infrastructure by default. Verified against a real in-process asyncua server.

## 0.6.0 — New verticals & protocols (PROFINET, energy, building, 信创) + intelligence

Breadth release: new field protocols and per-industry editions, China-market entry
artifacts, and two new read-only intelligence layers. Same read-first stance and
preview / mock-or-sim caveat. (Also includes a code-review hardening pass — see below.)

### Added — intelligence layer
- **Data-quality watchdog** — `data_quality_scorecard` (fleet data-TRUST rollup:
  scores each tag 0-100 on staleness / **dead heartbeat** / bad-quality / flatline /
  gaps / anomaly, rolled up per endpoint + fleet with ranked worst offenders) and
  `heartbeat_health` (first-class watchdog-liveness check). Pure analysis; also feeds
  the downtime root-cause copilot. CLIs `iaiops diag dataquality` / `iaiops diag heartbeat`.
- **UNS governance** — `uns_topic_audit` (UNS naming conformance + topic-sprawl:
  casing collisions, scattered leaves, depth outliers, duplicates → clean/minor/
  sprawling) and `uns_schema_drift` (Sparkplug NBIRTH baseline-vs-current →
  none/additive/breaking). CLIs `iaiops mqtt uns-audit` / `iaiops mqtt uns-drift`.

### Fixed (code-review hardening)
- **`iec61850` extra had a fabricated version pin** (`>=1.5` — uninstallable; PyPI tops
  out at 0.12.x) that broke `iaiops[energy]` resolution → corrected to `>=0.10,<1`.
- **`secsgem` was missing from `SUPPORTED_PROTOCOLS`** since v0.4.0 — config rejected
  every secsgem endpoint, making that connector unreachable → fixed + fully wired into
  the capability map.
- **RCA copilot crashed on mixed naive/aware timestamps** (operator's naive `start` vs a
  device's `...Z` alarm) → timestamp parsing now coerces naive→UTC everywhere.
- **PROFINET / BACnet / IEC-104 raised raw tracebacks** on the most common real failure
  (raw-socket permission / UDP bind) because the client was built outside the session
  `try` → builds moved inside; failures now translate to teaching errors.
- **SQL-injection hole** in the TDengine sink (unescaped timestamp; identifiers) → fixed.
  Plus: DNP3 integrity-poll harvested the wrong handler; IoTDB wrote local-tz/epoch-0;
  chattering alarms inflated RCA confidence; live sink errors escaped the error contract.
  15 regression tests added for the previously-untested paths.

### Fixed (binding validation pass, 2026-06-30)
Ran the preview/待核实 bindings against **real libraries + containerized servers**
(not mocks) — which surfaced three real bugs the mock suite could never catch:
- **`iec61850` extra pointed at the wrong PyPI distribution.** The prior pin
  `iec61850>=0.10,<1` resolves to an unrelated async-OOP client that exposes **none**
  of the `IedConnection_*` SWIG symbols the driver calls (0/14). Re-pinned to
  **`pyiec61850`** (the real libiec61850 SWIG binding, linux-only wheel); all 14
  driver symbols verified present, and the driver/connection imports now use it.
- **BACnet called a fabricated `whois()`** — BAC0 exposes `who_is()`; the mock fake
  duck-typed the wrong name, so it would have `AttributeError`'d against real gear.
- **TDengine `CREATE STABLE` used `value` as a column name** — a TDengine reserved
  word the live parser rejects with a syntax error → back-quoted in DDL.
- **Verified live:** IEC-104 (real c104 loopback link via `iec104_session`), IoTDB &
  TDengine (write→read round-trip via the real sinks). **Still 待核实:** DNP3
  (`pydnp3` has no wheel + needs a live outstation) and live-RTU/IED reads.
- **New guards:** `tests/test_binding_contracts.py` (per-binding library-API contract
  tests, `importorskip`-gated — run when an extra is installed) and
  `tests/test_protocol_consistency.py` (cross-registry meta-test that would have caught
  the historical `secsgem`-missing-from-`SUPPORTED_PROTOCOLS` regression).

### Added — verticals & protocols
- **PROFINET connector (read-only)** — layer-2 **PROFINET-DCP** discovery/identify
  via the optional `pnio-dcp` extra (`pip install iaiops[profinet]`):
  `profinet_discover` (DCP IdentifyAll — one broadcast surfaces every station on the
  segment), `profinet_identify_station` (by name-of-station), `profinet_station_params`
  (targeted DCP Get by MAC), and `profinet_asset_inventory` (register with
  IO-controller/IO-device role decoding). **Discovery + identify only** — no RT cyclic
  process data, and the disruptive DCP *Set* services (set-name/ip/blink/reset) are not
  exposed. Needs raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the PROFINET
  subnet; added to the `factory` profile + bundle. Mock-tested, not yet hardware-verified.
- **Energy edition** — three read-only substation/utility telecontrol connectors,
  an `energy` MCP profile (`IAIOPS_MCP=energy`), and the `iaiops[energy]` bundle:
  - **IEC 60870-5-104** (`iaiops[iec104]`, `c104`): `iec104_connection_info`,
    `iec104_interrogate` (general interrogation), `iec104_read_point`.
  - **DNP3** (`iaiops[dnp3]`, `pydnp3`/opendnp3): `dnp3_link_status`,
    `dnp3_integrity_poll` (Class 0/1/2/3 database grouped by measurement type).
  - **IEC 61850 MMS** (`iaiops[iec61850]`, libiec61850): `iec61850_device_directory`,
    `iec61850_browse`, `iec61850_read` (object-reference + functional constraint).
  - **Monitor direction only** — control commands (C_SC/C_DC, CROB, Oper/SBO) and
    IEC-61850 GOOSE/SV are not exposed. **⚠️ Preview / 待核实**: library bindings are
    unverified against live RTUs/IEDs and kept out of `iaiops[all]` (iec61850 needs
    libiec61850 built; pydnp3 builds a native ext). Largest validation debt in the line.
- **Building edition** — **BACnet/IP** (ASHRAE 135) read-only facility/HVAC monitoring
  via the `iaiops[bacnet]` extra (BAC0/bacpypes3), the `building` MCP profile
  (`IAIOPS_MCP=building`), and the `iaiops[building]` bundle: `bacnet_discover`
  (Who-Is), `bacnet_object_list`, `bacnet_read_property`, `bacnet_read_points`
  (present-value snapshot of analog/binary/multistate points). Read-only — present-value
  writes are not exposed. **⚠️ Preview / 待核实**: BAC0 binding unverified against live gear.
- **信创 / China entry** — `compliance_mapping` (《工控系统网络安全防护指南》 ↔ iaiops
  governance self-assessment with honest per-control status), a national-TSDB
  historian sink `historian_push` (write collected telemetry to **TDengine**
  `iaiops[tdengine]` or **Apache IoTDB** `iaiops[iotdb]` — data egress to the
  operator's own historian, not a control write), CLIs `iaiops compliance` /
  `iaiops historian push`, and **docs/CHINA.md** (air-gapped wheelhouse install,
  国产 OS/芯/PLC validation matrix, compliance reference). **⚠️ 待核实**: 国产
  OS/芯/PLC and the TSDB write paths are documented but not hardware-verified.

### Notes
- 90 tools across 14 protocols (incl. 2 信创/compliance + 4 new intelligence tools).
  Still **preview** — mock/sim validated; the energy, building, and 信创 paths are
  unverified against live equipment (see docs/CHINA.md for the validation backlog).

## 0.5.0 — AI downtime root-cause copilot

The flagship cross-protocol intelligence step: orchestrate the existing read
tools + brain into an **evidence-cited, advisory** root-cause verdict for a
downtime/incident window. Read-first, mock/sim preview — unchanged stance.

### Added
- **`downtime_root_cause`** (brain `iaiops/core/brain/rca.py`, MCP tool, and
  `iaiops diag rca`) — correlates whatever evidence a site supplies (alarm events,
  tag samples, a `diagnose_dataflow` verdict, a machine-state series) around an
  incident window and ranks candidate causes. Highlights:
  - **Temporal correlation** — a cause precedes its effect, so signals *before*
    onset (within a configurable `lead_window_s`) outweigh signals *during* it;
    signals *after* onset are treated as consequences.
  - **Confidence by noisy-OR** (`1 − Π(1−wᵢ)`) — independent, agreeing evidence
    compounds toward (never reaching) certainty; a lone weak signal stays weak.
  - **Anti-hallucination** — every citation references a real supplied signal;
    thin evidence downgrades to `insufficient_evidence` with a concrete
    `recommended_next_data` list instead of a confident guess.
  - **Advisory / read-only** — proposes a human-approved, MOC-gated, undoable
    next step per cause; executes nothing.
- **`downtime_root_cause_live`** (brain `iaiops/core/brain/rca_collect.py`, MCP
  tool, and `iaiops diag rca-live`) — the copilot that **gathers its own evidence**:
  give it an endpoint + window + refs and it pulls a cross-protocol
  `diagnose_dataflow` probe, a short sampled series per ref (feeding `tag_health`),
  and active OPC-UA conditions, then runs the same advisory analysis. The gathered
  bundle is echoed under `collected_evidence`; reuses only existing read paths, adds
  light read load, and degrades (never raises) on a partial outage.

### Notes
- 68 tools across 9 protocols (7 cross-protocol diagnostics). Still **preview** —
  validated against simulators / mocks, not live equipment.

## 0.4.0 — Industrial-AIOps

First release under the standalone **`industrial-aiops`** org (split out of the
`AIops-tools` IT line). Same governance harness, read-first stance, and preview /
mock-or-sim validation caveat — now a monorepo with a shared core, per-protocol
connectors, a menu-configurable MCP, and a semiconductor/display fab connector.

### Breaking
- **Renamed `ot-aiops` → `iaiops`**: package `ot_aiops`→`iaiops`, CLI/MCP
  `ot-aiops`→`iaiops`, env `OT_AIOPS_*`→`IAIOPS_*`, home `~/.ot-aiops`→`~/.iaiops`.
  Legacy env vars and the legacy home directory are honored as a fallback so
  existing installs keep unlocking secrets / reading audit.
- **Protocol client libraries are now optional extras** — the base package installs
  and imports without them; install only what a site runs:
  `pip install "iaiops[opcua,modbus]"` (or `iaiops[all]`). A call to a
  not-installed protocol returns a teaching error pointing at the right extra.

### Added
- **Shared core** — `iaiops/core/{governance,runtime,brain}`; connectors import it.
- **`IAIOPS_MCP` menu** — expose only the protocols a site runs (named profiles
  `all` / `fab` / `factory` / `process`, or a comma list). `fab` profile = 29 tools
  vs 66 for `all`.
- **SECS/GEM connector** — host-side reads for semiconductor/display fab equipment
  over HSMS (SEMI E5/E30/E37) via the `secsgem` extra: equipment status, SVID/ECID
  namelists + values, alarms, process programs (7 tools).
- **OPC-UA connection self-diagnosis** (`opcua_diagnose_connection`) — classifies a
  failed connect (certificate / security policy / auth / firewall / dns / port /
  config) with the fix; wired into `iaiops doctor`.
- **`subscription_health`** — sequenced-feed loss/reorder/overload (OPC-UA monitored
  items or Sparkplug B): sequence gaps, republish-rejection rate, overloaded channels.
- **Per-industry edition bundles** — `iaiops[fab]` / `iaiops[factory]` / `iaiops[process]`.

### Notes
- 66 tools across 9 protocols. Still **preview** — validated against simulators /
  mocks, not live equipment.
