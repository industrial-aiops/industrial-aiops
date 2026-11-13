# Handoff verification — 2026-11-13

Baseline: release commit `513951e`; package reports `iaiops 0.33.0`.
Changes in this handoff are documentation and a demo launcher only.

- Fresh isolated virtual environment: Python 3.13.12 on macOS, installed local
  source with the `modbus` extra using uv. Ubuntu/pip commands are provided but
  were not exercised on an Ubuntu guest in this handoff.
- Full `bash deploy/igel/evaluation/run-demo.sh`: exit 0; 867 stored samples
  across three tags; deliberate TCP server interruption; standalone HTML
  report generated. Counts/timings vary. Synthetic line, no physical PLC.
- `pytest -q tests/test_demo_script.py tests/test_profiles.py`: 29 passed.
- `ruff check .`: passed; `ruff format --check .`: 682 files formatted.
- `bandit -q -r iaiops mcp_server --severity-level medium`: exit 0, no Medium+
  findings (existing comment-parsing warnings).
- `bash -n deploy/igel/evaluation/run-demo.sh` and `git diff --check`: passed.

No full regression suite was rerun for these documentation/launcher changes.
No IGEL/UMS/IMH/IMC, external MCP client, traffic-monitor integration or
physical-device validation was performed. See README.md for the next exercise.

## Joint traffic demo source update — 2026-11-13

The handoff now also includes `demo/joint-traffic/`, and `run-demo.sh` launches
that exercise. These are source-only updates; the installed package and
published image remain 0.33.0.

- Default 90-second scenario / 93-second collection on macOS, Python 3.13.12,
  pymodbus 3.16.2: exit 0; **1,056 samples**, one connection-cut blind interval.
  Existing OEE engine reports **13.4s observed stopped**, **18.1s unobserved**,
  **80.51% observed-time coverage**. These are synthetic run results, not plant
  performance. Successful-attempt coverage is separately 92.47%; its denominator
  differs from time coverage.
- Fixture ticks continue incrementing during the relay cut. The local report
  imports **zero** external monitor events and makes no monitor-health claim.
- End-to-end socket tests cover valid stop observations, a blind window,
  continued fixture counters, recovery, rejection of public Modbus writes,
  cleanup of both listeners on cancellation, config isolation, evidence-source
  separation, CSV identity/timezone/schema validation, HTML escaping, and
  protection of existing output directories.
- `pytest -q tests/test_joint_traffic_demo.py tests/test_demo_script.py
  tests/test_profiles.py`: **39 passed**. Full product regression not rerun.
- `ruff check .`, `ruff format --check .`, shell syntax and whitespace checks
  passed. Bandit scan includes the new demo, with zero Medium+ findings.
- Generated report rendered in headless Chrome and visually inspected. Sample
  counts/timings vary; no OEE percentage is an acceptance threshold.

Only local software sockets have been exercised. The separate-host commands,
Linux/Ubuntu guest, IMH/IMC deployment, real monitor visibility/export, actual
cross-host clock alignment and physical PLCs remain **待核实**. The relay closes
application TCP connections; no firewall DROP or real packet-loss test was run.
