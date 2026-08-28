#!/usr/bin/env bash
# Reproducible harness for tests/test_mtconnect_agent_live.py — rung 2a.
#
# Everything else in the MTConnect suite talks to a server we wrote. That proves
# our parser reads what we emit. It cannot show what the REFERENCE agent emits,
# and the difference was not cosmetic: cppagent streams its own `Agent` device
# alongside the machines, with Availability AVAILABLE whenever it is answering.
# Our fixtures had one device and no Agent stream, so `mtconnect oee` picking
# data items by type across the whole document looked correct for years.
#
# This brings up the real thing (mtconnect/agent, the MTConnect Institute's
# cppagent) with a two-machine device model — the configuration under which the
# defect is visible — and exports the URL the test reads.
#
# Usage:
#   scripts/mtconnect_agent_harness.sh          # start, print the export line
#   scripts/mtconnect_agent_harness.sh stop     # tear down
set -euo pipefail

NAME="${IAIOPS_MTCONNECT_CONTAINER:-iaiops-mtc-agent}"
PORT="${IAIOPS_MTCONNECT_PORT:-5000}"
IMAGE="${IAIOPS_MTCONNECT_IMAGE:-mtconnect/agent:latest}"
CONFIG_DIR="$(mktemp -d)"

if [ "${1:-start}" = "stop" ]; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  echo "stopped $NAME"
  exit 0
fi

device() {  # $1 = suffix (1 or 2)
  cat <<XML
    <Device id="d$1" name="VMC$1" uuid="vmc-00$1">
      <DataItems>
        <DataItem category="EVENT" id="avail$1" type="AVAILABILITY"/>
      </DataItems>
      <Components>
        <Controller id="ctrl$1" name="controller">
          <DataItems>
            <DataItem category="EVENT" id="cmode$1" type="CONTROLLER_MODE"/>
          </DataItems>
          <Components>
            <Path id="path$1" name="path">
              <DataItems>
                <DataItem category="EVENT" id="execution$1" type="EXECUTION"/>
                <DataItem category="EVENT" id="program$1" type="PROGRAM"/>
              </DataItems>
            </Path>
          </Components>
        </Controller>
      </Components>
    </Device>
XML
}

cat > "$CONFIG_DIR/Devices.xml" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<MTConnectDevices xmlns="urn:mtconnect.org:MTConnectDevices:2.0"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="urn:mtconnect.org:MTConnectDevices:2.0 http://schemas.mtconnect.org/schemas/MTConnectDevices_2.0.xsd">
  <Header creationTime="2026-01-01T00:00:00Z" sender="iaiops-harness" instanceId="1"
          version="2.0" bufferSize="131072"/>
  <Devices>
$(device 1)
$(device 2)
  </Devices>
</MTConnectDevices>
XML

cat > "$CONFIG_DIR/agent.cfg" <<CFG
Devices = /mtconnect/config/Devices.xml
Port = 5000
AllowPut = true
SchemaVersion = 2.0
CFG

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "$PORT:5000" -v "$CONFIG_DIR:/mtconnect/config" "$IMAGE" >/dev/null

# The agent binds after it loads the device model; poll rather than sleep, so a
# slow image pull on a cold runner does not present as a broken harness.
for _ in $(seq 1 30); do
  if curl -fsS -m 2 "http://127.0.0.1:$PORT/probe" >/dev/null 2>&1; then
    echo "agent up on $PORT (device model: VMC1 + VMC2, no adapter connected)"
    echo "export IAIOPS_MTCONNECT_AGENT_URL=http://127.0.0.1:$PORT"
    exit 0
  fi
  sleep 1
done

echo "agent did not answer /probe within 30s" >&2
docker logs "$NAME" 2>&1 | tail -20 >&2
exit 1
