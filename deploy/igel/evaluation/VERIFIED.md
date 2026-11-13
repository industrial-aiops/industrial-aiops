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
