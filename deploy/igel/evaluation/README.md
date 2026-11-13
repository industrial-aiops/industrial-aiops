# Industrial-AIOps 0.33.0 — integration evaluation

A small, source-based handoff for testing Industrial-AIOps alongside an edge
traffic-monitoring application. Baseline: release commit `513951e` (0.33.0).
No UMS installer, licence, credentials or customer data is included.

## 1. Get the source

```bash
git clone --depth 1 --branch delivery/igel-evaluation-033 \
  https://github.com/industrial-aiops/industrial-aiops.git
cd industrial-aiops
```

Alternatively extract the supplied source archive and enter its top directory.
Use a Linux machine or Ubuntu guest for the first run; Python 3.11+ and Bash
are required. A fresh install needs Internet access to resolve Python dependencies.
This is not an offline dependency bundle or a native IGEL application package.

## 2. Install

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install '.[modbus]'
.venv/bin/iaiops --version
```

Expected version: `iaiops 0.33.0`. Keep the virtual environment in this directory;
the demo launcher below uses it. On Ubuntu, install the venv package matching
your Python version if `python3 -m venv` is unavailable.

## 3. Run the software-only demo

```bash
bash deploy/igel/evaluation/run-demo.sh
```

Allow about two minutes. No PLC, account, GPU, LLM or cloud service is required.
The launcher clears inherited configuration variables; the underlying demo uses
a temporary HOME and a local pymodbus TCP server on `127.0.0.1`, with synthetic
production data. It performs real TCP reads, deliberately kills and restarts
that server, and then produces an OEE report and investigation output.
It does not discover or contact the plant network.

Open `dist/igel-evaluation/oee-demo.html` in a browser. A successful run exits
with code 0, reports collected samples and a blind window, and creates the HTML
report. The report distinguishes blind time from observed downtime. The exact
OEE varies with timing; it is not a measured customer result or a prediction.
See [the demo explanation](../../../demo/oee-line/README.md) for the sequence.

The simulator is temporary; it stops when the demo ends. The demo report is a
standalone HTML file that can be forwarded. Demo state stays in a temporary
directory; normal operation keeps local configuration and audit/data stores in
`~/.iaiops` unless explicitly relocated.

## 4. Connect an MCP client (optional, separate from the demo)

For an approved test endpoint, configure it interactively:

```bash
.venv/bin/iaiops init
.venv/bin/iaiops doctor --skip-probe
.venv/bin/iaiops doctor
.venv/bin/iaiops readiness
```

`doctor --skip-probe` checks configuration without contacting a device;
`doctor` probes the configured endpoints. Choose only the endpoints you intend
to test. Tag meaning and production roles require human confirmation.

For an MCP client that supports local stdio servers, merge this entry into its
configuration, replacing the absolute path:

```json
{
  "mcpServers": {
    "industrial-aiops": {
      "command": "/absolute/path/industrial-aiops/.venv/bin/iaiops",
      "args": ["mcp"],
      "env": {
        "IAIOPS_MCP": "factory",
        "IAIOPS_NO_EGRESS": "1"
      }
    }
  }
}
```

This starts a stdio MCP process; it does not open an HTTP API or listening port.
Ask the client to inspect site readiness first. No-egress withholds the optional
data-export tools; it still permits configured device reads and is not a
read-only enforcement switch. All tools retain their governance and audit gates.
The first joint exercise should use only reads. No PLC logic is written.

## 5. IGEL integration exercise

First reproduce this demo in a Linux environment. Then choose IMH or IMC based
on the intended use case with the IGEL team. A Linux guest is one candidate for
this source install; for a container candidate, the published image is
`ghcr.io/industrial-aiops/iaiops:0.33.0-factory`.
See [the deployment overlay](../README.md) for existing packaging materials.
Neither route is validated on an IGEL device by this handoff. Raw-L2 networking,
physical PLC operation, UMS deployment and licensing are outside this test.

A useful next joint test: observe the demo's local TCP connection and deliberate
outage alongside the traffic-monitoring application, then compare its event
timestamps with the collection blind window. Visibility into guest/container
loopback traffic depends on where the monitor runs and must be checked. If it
cannot see loopback, a separate approved lab-network scenario is needed.
No integration between the two products is claimed yet.

Please send back: OS/Python versions, install/demo outcome, the HTML report,
and any sanitised error output. Do not send credentials or customer addresses.

## Verification limits

See [VERIFIED.md](VERIFIED.md) for the checks performed on this handoff.

Software TCP/simulator evidence is not physical-device evidence. Current
protocol limits are recorded in
[VERIFICATION-RECORD.md](../../../docs/VERIFICATION-RECORD.md).
The Margo descriptor and any supplier packaging checks do not establish IGEL
certification or runtime compatibility. Newer branch-only OTLP telemetry and
Margo archive corrections are deliberately excluded from this release baseline.
