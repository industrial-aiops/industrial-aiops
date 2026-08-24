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

# Report knobs. LANG_ rather than LANG: LANG is a POSIX locale variable and
# overwriting it here would change how every child process formats and sorts.
SITE="${SITE:-Plant A}"
LANG_="${IAIOPS_REPORT_LANG:-en}"
REPORT_OUT="${REPORT_OUT:-$PWD/oee-demo.html}"

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
# The note is the one from README.md, carried onto the page itself. A forwarded
# report of a shift compressed into seventy seconds, WITHOUT that sentence, reads
# as a real plant's real OEE — the exact overstatement this tool exists to
# refuse, committed by its own demo. It belongs on the artefact, not only in a
# README nobody forwards alongside it.
# It follows --lang. The first version of this hardcoded the English text, so the
# Chinese report carried an English caveat — which is worse than no caveat, since
# a reader who cannot read it will scroll past the one paragraph that stops the
# number being taken literally.
if [ "$LANG_" = "zh" ]; then
  NOTE="形状是真的,数字不是对任何人工厂的断言。这个班次被压缩到 ${DURATION} 秒,\
所以损失的比例远大于真实产线 —— 公开的「人工记录 vs 实测 OEE」基准把真实差距放在 \
8-12 个百分点。这份 demo 真正证明的是**机制**:短到写不下来的停机被算进去了,\
而盲区时间没有被算成停机。"
else
  NOTE="The shape is real. The numbers are not a claim about anybody's plant. This \
shift is compressed into ${DURATION} seconds, so its losses are proportionally far \
larger than a real line's — published benchmarking of manual-vs-measured OEE puts \
the real-world gap at 8-12 points. What this legitimately shows is MECHANISM: that \
stoppages too short to write down are counted, and that blind time is not."
fi

HOME="$DEMO_HOME" $IAIOPS oee measure line1 --reported "$REPORTED" \
  --minor-stop-s "$MINOR_STOP_S" \
  --site "$SITE" --lang "$LANG_" --note "$NOTE" \
  --report "$DEMO_HOME/oee.html"

# Out of the temp home and into the working directory, because a report you
# cannot find is a report you cannot forward — and forwarding it is the point.
if [ -f "$DEMO_HOME/oee.html" ]; then
  cp "$DEMO_HOME/oee.html" "$REPORT_OUT"
  echo
  echo "════ The thing you can actually hand to someone ════"
  echo "  $REPORT_OUT"
  echo "  Self-contained: no fonts, scripts, styles or images from anywhere, and"
  echo "  no network request when opened. Works on an air-gapped laptop."
fi

echo
echo "[demo] isolated home was $DEMO_HOME — your own config and store were untouched."
