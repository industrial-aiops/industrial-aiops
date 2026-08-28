#!/usr/bin/env bash
# Reproducible harness for tests/test_discovery_eip_live.py — rung 2a for the
# EtherNet/IP IDENTIFICATION path only.
#
# `tests/eip_plc_harness.py` is a CIP PLC we wrote, so it can only confirm that
# our reading matches our own understanding of the spec — its own docstring says
# so. `cpppo` is somebody else's EtherNet/IP stack. It answers ListIdentity as a
# `1756-L61/B LOGIX5561`, which is what a discovery pass is entitled to ask.
#
# It does NOT close the Logix TAG layer: cpppo implements the Identity object
# but not the Logix-specific objects `pycomm3.LogixDriver` needs on open() —
# 0x64 (program name) returns a reply pycomm3 cannot parse, and 0x6B/0x6C drop
# the connection. So `test_eip_live.py` stays at 2b and a physical
# ControlLogix stays rung 3. Recorded here so the next person does not spend the
# afternoon rediscovering it.
#
# Usage:
#   scripts/enip_simulator_harness.sh          # start, print the export line
#   scripts/enip_simulator_harness.sh stop     # tear down
set -euo pipefail

PORT="${IAIOPS_ENIP_PORT:-44818}"
PIDFILE="${TMPDIR:-/tmp}/iaiops-enip-sim.pid"

if [ "${1:-start}" = "stop" ]; then
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "stopped"
  exit 0
fi

if ! python3 -c "import cpppo" 2>/dev/null; then
  echo "cpppo is not installed in this interpreter: pip install cpppo" >&2
  exit 1
fi

python3 -m cpppo.server.enip -a "127.0.0.1:$PORT" \
  "Motor_Speed=INT[10]" "Tank_Level=REAL[5]" "Running=BOOL[1]" \
  >"${TMPDIR:-/tmp}/iaiops-enip-sim.log" 2>&1 &
echo $! > "$PIDFILE"

for _ in $(seq 1 20); do
  if python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)
" 2>/dev/null; then
    echo "cpppo EtherNet/IP simulator up on $PORT"
    echo "export IAIOPS_ENIP_HOST=127.0.0.1"
    exit 0
  fi
  sleep 1
done

echo "simulator did not accept a connection within 20s" >&2
tail -20 "${TMPDIR:-/tmp}/iaiops-enip-sim.log" >&2
exit 1
