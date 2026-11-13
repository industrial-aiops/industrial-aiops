#!/usr/bin/env bash
# Run the existing software-only demo with no inherited iaiops configuration.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ ! -x "$ROOT/.venv/bin/iaiops" ]]; then
  echo "Install first: see deploy/igel/evaluation/README.md" >&2
  exit 1
fi
mkdir -p "$ROOT/dist/igel-evaluation"
cd "$ROOT"
env -i PATH="$PATH" HOME="$HOME" \
  PY="$ROOT/.venv/bin/python" IAIOPS="$ROOT/.venv/bin/iaiops" \
  IAIOPS_NO_EGRESS=1 \
  REPORT_OUT="$ROOT/dist/igel-evaluation/oee-demo.html" \
  bash demo/oee-line/run_demo.sh
