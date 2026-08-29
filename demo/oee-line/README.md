# OEE demo — a real Modbus line, including the parts that go wrong

```bash
./demo/oee-line/run_demo.sh
```

About two minutes, no hardware, nothing installed beyond the package. It runs the
commands a site runs, in order, against a **real pymodbus TCP server** — real sockets, real FC03
reads, real decoding — and kills the device part-way through.

## ⚠️ Read this before showing it to anyone

**The shape is real. The numbers are not a claim about anybody's plant.**

The shift is compressed into ~70 seconds, so its losses are proportionally far
larger than a real line's: the demo typically reports a gap of 20+ points against
the "reported" figure, where published benchmarking of manual-vs-measured OEE
puts the real-world gap at 8–12 points (`docs/MARKET-EVIDENCE.md` §3, itself
marked 待核实). Quoting the demo's percentage as an expected result would be
exactly the kind of flattering overstatement the tool is built to refuse.

What the demo legitimately shows is **mechanism**: that stoppages too short to
write down are counted, that blind time is not, and that the tool reports what is
there rather than what would sell.

## What it runs

| | command | contacts a device? |
|---|---|---|
| 1 | `iaiops scan plan` | **no** — the worst case, and the refusals, before a packet is sent |
| 2 | `iaiops readiness` | **no** — what this site can run, and what each gap needs |
| 3 | `iaiops tags export` | **no** — the point list, with the `role` column **empty** |
| 4 | `iaiops tags apply --by` | **no** — a config patch to merge; nothing is written for you |
| 5 | `iaiops collect plan` | **no** — what a run would cost, and what it could not see |
| 6 | `iaiops collect run` | yes — a bounded assessment run |
| 7 | `iaiops oee measure --since/--until --report` | **no** — measured over collected history |
| 8 | `iaiops investigate open` | **no** — the window is already past |

**Seven of the eight contact nothing.** That is the point of ordering them this
way: you can answer "what would this take, and what would it find" on a site you
have not been given permission to probe.

**Steps 2-4 are the sequence worth watching.** The demo starts with tags and no
roles — what a site actually has after `iaiops init`. `readiness` reports OEE as
blocked; `tags export` hands you a sheet whose `role` column is empty *next to a
tag called "Good-parts counter"*; a person fills it in; only then is the figure
computable. A demo that started from a pre-configured endpoint would hide the one
step this product refuses to take for you.

Step 7 passes `--since` / `--until` around the collection it just did. Without a
window the measurement covers everything the store holds for that endpoint, which
is right for one run and wrong the moment there are two.

## What you can hand to someone afterwards

Step 7 writes **`oee-demo.html`** into the directory you ran it from — one
self-contained file with the whole story: what the measurement could see, the
A×P×Q figure, the Six Big Losses, the gap against the site's own number, and the
prerequisite row saying what had to be declared to produce each figure.

It loads no fonts, scripts, styles or images from anywhere and makes no network
request when opened, so it works on an air-gapped laptop in a plant office and
survives being forwarded as an attachment.

**The caveat above travels with it.** The paragraph at the top of this README is
rendered onto the page itself, near the top, before the number. A forwarded
report of a shift compressed into seventy seconds — without that sentence — reads
as a real plant's real OEE, which is the exact overstatement this tool exists to
refuse, committed by its own demo.

```bash
IAIOPS_REPORT_LANG=zh ./demo/oee-line/run_demo.sh   # the report in Chinese
REPORT_OUT=~/Desktop/oee.html ./demo/oee-line/run_demo.sh
```

## The outage is the demo

At `OUTAGE_AT` the script **kills the server process**. Not a flag, not a mock —
a genuine `Connection refused`, chosen so the collector meets the failure a plant
network actually produces.

It lands inside a **running** stretch on purpose. That is the case worth showing:
the line was producing the whole time, the tool simply could not see it, and the
measurement must not call that downtime.

```
Collected 558 samples (84.29% of intended)
Blind for 1 window(s):
  · 01:36:36 → 01:36:46  (100 missed) OTConnectionError: Could not connect …

  71.19% over 84.29% coverage
  running 42s · stopped 17s · blind 11s
  3 minor stoppage(s) totalling 7s — under 5s each, the ones a manual tally cannot see
```

Counting that blind window as downtime would have moved availability several
points in the direction that flatters the seller. That is the error to look for
in any tool making this claim, including this one.

## The config is the whole semantic ask

```yaml
tags:
  - ref: "0"
    role: run_state
    running_when: [2]     # ← stated, never inferred
  - ref: "10"
    role: total_count
  - ref: "11"
    role: good_count
```

Two tags. `running_when` is mandatory because this status word is
`0=stopped 1=idle 2=running 3=fault`, and "anything non-zero" would count idle
and fault as production — inflating availability and OEE.

## Knobs

| variable | default | |
|---|---|---|
| `DURATION` | 70 | seconds of compressed shift |
| `INTERVAL_MS` | 200 | sample rate — sets the shortest visible stop (2×) |
| `OUTAGE_AT` / `OUTAGE_FOR` | 28 / 10 | when the device dies, and for how long |
| `MINOR_STOP_S` | 5 | scaled to the compressed shift, not the 300s default |
| `REPORTED` | 97 | the figure the "site" believes |

`MINOR_STOP_S` matters: at the 300s default every stop in a 70-second shift is
"minor", including the long one, and the story comes out backwards.

## Isolation

Everything runs under a temporary `HOME`, so your own `~/.iaiops/config.yaml`,
data store and audit log are untouched. The port is chosen free at random.
