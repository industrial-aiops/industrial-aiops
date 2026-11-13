#!/usr/bin/env bash
# Joint production-state / communication exercise; no external monitor assumed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ ! -x "$ROOT/.venv/bin/iaiops" ]]; then
  echo "Install first: see deploy/igel/evaluation/README.md" >&2
  exit 1
fi
cd "$ROOT"
exec "$ROOT/.venv/bin/python" demo/joint-traffic/joint_demo.py local \
  --duration 90 --run-id joint-demo-1 --out dist/joint-demo-1 "$@"
