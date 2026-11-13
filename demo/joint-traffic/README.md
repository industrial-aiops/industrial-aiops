# Joint demo: production stop or communication blind spot?

Source handoff for an Industrial-AIOps / traffic-monitoring lab exercise.
No physical PLC, GPU, LLM, UMS API or proprietary monitor SDK is required.
IGEL compatibility and the capabilities of the IGEL lab monitor remain **待核实**.

## What the audience sees

A synthetic Modbus TCP line exposes three explicitly authored points:
run state (`0`: 2=running, 0=stopped), total count (`10`), good count (`11`).
These meanings are fixture definitions, not agent-confirmed plant semantics.

| Part of scenario | Production | TCP relay | Expected collector evidence |
|---|---|---|---|
| 0–20% | Running | Open | Running state; growing count |
| 20–35% | Stopped | Open | Valid stop-state samples; counter holds |
| 35–55% | Running | Open | Production resumes |
| 55–75% | Running | Cut | Collection gap; no claim about real production state |
| 75–100% | Running | Open | Reads recover; counter has advanced |

The relay closes the existing collection connection and closes newly accepted
connections during the cut. It is an **application-level TCP cutoff**, not a
firewall DROP, packet-loss injection, switch outage or captured monitor finding.
The backend server and local fixture driver stay alive and continue counting.
A passive monitor may see connection closes/reconnects, but the exact signal
must be checked in its actual deployment. No root cause is inferred from silence.

The public relay forwards only FC03 single-register reads of 0, 10 or 11.
Writes and other requests are rejected. The fixture driver writes only to the
private loopback software simulator, never to an external device. No OS firewall,
production routes or PLC logic is changed.

## Install once, on each participating Linux machine

From the repository root, using Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install '.[modbus]'
.venv/bin/iaiops --version
```

The iaiops package remains 0.33.0. These scripts are source-only handoff updates,
not a new PyPI or container release. The existing published container does not
include this new orchestration; start with the source install in a Linux lab.

## A. First run: one machine, about two minutes

```bash
.venv/bin/python demo/joint-traffic/joint_demo.py local \
  --duration 90 --run-id joint-demo-1 --out dist/joint-demo-1
```

Outputs must be new or empty directories; reruns use a new directory/run ID.
Starts a loopback-only server, waits for readiness, runs governed iaiops CLI
collection, exports samples, computes OEE, and produces a shared timeline.
No external traffic monitor is invoked or fabricated. No plant network is scanned.

Open `dist/joint-demo-1/collector/joint-report.html`, then the linked OEE detail.
Look for stop-state observations during the production stop, a collection blind
window during the relay cut, and resumed running samples. Numeric timing and
OEE are synthetic and vary. Local run data/config/audit state stays under the
output directory's `collector/home`; existing `~/.iaiops` is not used.

The one-machine test uses loopback. A monitor outside the guest/container may
not see it; this is why the two-machine exercise below is the joint-demo target.

## B. Joint run: simulator B, collector A, monitor sees their path

```text
B: loopback simulator + local fixture driver
       |
   read-only relay (B_LAB_IP:15020)
       |                <-- IGEL monitors this inter-workload TCP path
A: iaiops collection --> samples, gaps, OEE, report
```

Agree an isolated lab segment and two test hosts/VMs/containers. Choose IMH or
IMC with the IGEL team according to the available visibility and networking; this
handoff does not assume either route has already been validated. No raw-L2
protocols or privileged packet capture are needed by the demo itself.

1. Synchronize A, B and the monitor's clocks to UTC and record any known skew.
   If skew is unknown, do not interpret cross-host timestamp alignment as evidence.
2. On B, replace `B_LAB_IP` with B's explicit numeric lab IP (not `0.0.0.0`):

```bash
.venv/bin/python demo/joint-traffic/joint_demo.py simulator \
  --bind B_LAB_IP --port 15020 --lab-network \
  --duration 90 --run-id joint-demo-1 --out dist/joint-demo-1-simulator
```

Wait for `Ready ... waiting for first valid read`. It waits up to 300 seconds
for a collector. The scenario clock starts on the first allowed read, not on
process launch. Avoid a Modbus health probe before the planned collection.
`ready.json` records the listening IP/port. Ctrl+C cleans up the backend process.
The simulator exits automatically about five seconds after the scenario ends.

3. The IGEL team configures the monitor to observe A↔B TCP traffic on port 15020.
   This is a required visibility check, not a capability established by this demo.
4. On A, replace `B_LAB_IP` with exactly the same numeric address:

```bash
.venv/bin/python demo/joint-traffic/joint_demo.py collect \
  --host B_LAB_IP --port 15020 --lab-network \
  --duration 93 --run-id joint-demo-1 --out dist/joint-demo-1-collector
```

The collector reads only this explicit fixture endpoint. Installation is online;
the runtime test needs no cloud. Monitor placement, switch mirroring and IGEL
network configuration are part of the IGEL lab setup, not changes made by this script.

## C. Combine actual exported evidence

Copy B's `simulator-events.jsonl` and an actual monitor CSV to A. There is no
automatic monitor API integration. Normalize the monitor's export to this schema
using the included header-only `monitor-events-template.csv`:

```text
ts,run_id,host,port,message
```

- `ts`: ISO-8601 with explicit timezone, preferably UTC (`...+00:00` or `...Z`).
- `run_id`: the shared run ID; `host` and `port`: B's exact configured IP and 15020.
  Map from the monitor's original source/destination tuple without guessing an asset.
- `message`: the monitor's actual finding, e.g. its connection event description.
  Do not turn relay-control records into monitor findings. Preserve original exports.
- A CSV with only the header is valid: zero monitor events means **no imported
  monitor evidence**, not a healthy network. Required fields/matching are checked.

From A, after copying files to the stated paths:

```bash
.venv/bin/python demo/joint-traffic/joint_demo.py report \
  --collector dist/joint-demo-1-collector \
  --simulator-events simulator-events.jsonl \
  --monitor-events monitor-events.csv \
  --clocks-synchronized
```

Pass `--clocks-synchronized` only after the human clock check. Without it the
report still lists supplied timestamps but marks synchronization unconfirmed;
there is no automatic event matching, diagnosis or root-cause assertion.
Monitor entries are labelled `monitor_import_unverified` because provenance and
content have not been independently verified by this script.

Deliverables in the collector directory:

| File | Evidence |
|---|---|
| `collection.json` | Actual collection counts, coverage and blind windows |
| `samples.csv` | Actual software-server reads, UTC timestamps |
| `oee.json`, `oee.html` | Existing iaiops OEE engine results |
| `run.json` | Shared run ID, explicit simulator address and collection window |
| `timeline.json`, `timeline.csv`, `joint-report.html` | Separate collector, fixture, relay-control and imported monitor rows |
| `home/` | Isolated config and local audit/data stores; inspect before sharing |

The simulator JSONL includes counter ticks during the outage, so the experimenter
can verify that synthetic production continued. **Only this independent fixture
truth establishes that fact**; the collector could not see inside the gap.
The HTML is self-contained apart from relative links to other local artifacts.
Share the report files together. It contains no external script/font requests.

## Joint acceptance checklist

- Stop interval has valid stopped-state samples while TCP reads keep succeeding.
- Relay-cut interval has collection blind time; it is not counted as observed downtime.
- Simulator counter ticks advance throughout that interval and reads recover afterwards.
- The IGEL team confirms visibility of the A↔B path and contributes real monitor events,
  or explicitly records that this visibility/feature is unavailable.
- The final timeline preserves evidence sources and clock status; a timestamp
  coincidence is not automatically promoted to a network root cause.

Local software checks are recorded in
[the handoff verification](../../deploy/igel/evaluation/VERIFIED.md).
No physical-device, Linux guest, IGEL or real-monitor validation follows merely
from a passing local run.
