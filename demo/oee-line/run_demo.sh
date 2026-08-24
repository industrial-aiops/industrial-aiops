#!/usr/bin/env bash
# End-to-end OEE demo against a REAL Modbus TCP device.
#
# Shows the four commands in the order a site would run them, and — deliberately
# — kills the device part-way through, because how the measurement handles blind
# time is the whole claim. A demo without the outage proves nothing.
#
# Everything is isolated under a temporary HOME, so it touches neither your real
# config nor your real data store.
set -euo pipefail
set +m            # no job-control 'Terminated' noise when the device is killed

IAIOPS="${IAIOPS:-.venv/bin/iaiops}"
PY="${PY:-.venv/bin/python}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DURATION="${DURATION:-70}"        # seconds of "shift"
INTERVAL_MS="${INTERVAL_MS:-200}"
# The outage lands inside a RUNNING stretch on purpose. That is the case worth
# showing: the line was producing the whole time, we simply could not see it —
# and the measurement must NOT call that downtime. An outage overlapping a real
# stoppage would muddle the very distinction the demo exists to make.
OUTAGE_AT="${OUTAGE_AT:-28}"      # kill the device here…
OUTAGE_FOR="${OUTAGE_FOR:-10}"    # …and bring it back after this
REPORTED="${REPORTED:-97}"        # the figure the "site" believes
# The shift is TIME-COMPRESSED, so the minor-stop threshold compresses with it.
# A real plant separates minor from major at ~300s in an 8-hour shift; this
# script's stops are ~2-3s (minor) against one ~14s (major), so 5s draws the same
# line. Leaving the 300s default here would file the long stoppage as "minor" and
# tell the story backwards.
MINOR_STOP_S="${MINOR_STOP_S:-5}"

DEMO_HOME="$(mktemp -d)"
PORT="$($PY -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
mkdir -p "$DEMO_HOME/.iaiops"

cleanup() { pkill -f "simulate_line.py .*--port $PORT" 2>/dev/null || true; }
trap cleanup EXIT

cat > "$DEMO_HOME/.iaiops/config.yaml" <<YAML
endpoints:
  - name: line1
    protocol: modbus
    host: 127.0.0.1
    port: $PORT
    unit_id: 1
    # 0.1s is what this simulated line actually runs at. It was 1.0 — ten times
    # too slow — and the demo dutifully printed "Performance computed to 1681.2%"
    # with a warning that the input was wrong. The tool was right; the demo was
    # showing a customer a nonsense number to prove it.
    ideal_cycle_time_s: 0.1
    tags:
      - ref: "0"
        label: "Line run state"
        role: run_state
        # 2 = running. Stated, never inferred: on this status word 1 is idle and
        # 3 is fault, and "anything non-zero" would count both as production.
        running_when: [2]
      - ref: "10"
        label: "Production counter"
        role: total_count
      - ref: "11"
        label: "Good-parts counter"
        role: good_count
YAML
chmod 600 "$DEMO_HOME/.iaiops/config.yaml"

echo "════ 1. What can this site run today?  (contacts nothing) ════"
HOME="$DEMO_HOME" $IAIOPS readiness 2>&1 | sed -n '1,12p'

echo
echo "════ 2. What would collection cost?  (contacts nothing) ════"
HOME="$DEMO_HOME" $IAIOPS collect plan line1 --duration "${DURATION}s" --interval-ms "$INTERVAL_MS"

echo
echo "════ 3. Collect from the live device ════"
$PY "$HERE/simulate_line.py" serve --port "$PORT" >/dev/null 2>&1 &
disown 2>/dev/null || true
sleep 2
$PY "$HERE/simulate_line.py" drive --port "$PORT" --duration "$DURATION" 2>/dev/null &

(
  sleep "$OUTAGE_AT"
  echo "  [demo] ✂︎  killing the device — a real outage, not a simulated one"
  pkill -f "simulate_line.py serve --port $PORT" 2>/dev/null || true
  sleep "$OUTAGE_FOR"
  echo "  [demo] ⏎  device back online"
  $PY "$HERE/simulate_line.py" serve --port "$PORT" >/dev/null 2>&1 &
  disown 2>/dev/null || true
) 2>/dev/null &

HOME="$DEMO_HOME" $IAIOPS collect run line1 \
  --duration "${DURATION}s" --interval-ms "$INTERVAL_MS"

echo
echo "════ 4. Measure it, against what the site believes ════"
HOME="$DEMO_HOME" $IAIOPS oee measure line1 --reported "$REPORTED" \
  --minor-stop-s "$MINOR_STOP_S"

echo
echo "[demo] isolated home was $DEMO_HOME — your own config and store were untouched."
