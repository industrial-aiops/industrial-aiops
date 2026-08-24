#!/usr/bin/env bash
# Reproducible harness for tests/test_opcua_cert_trust_live.py.
#
# The question it answers: does certificate TRUST actually gate a session, and
# does the connector's diagnosis name the right cause when it does? That cannot
# be asked of the in-process asyncua server the other OPC-UA tests use — it runs
# a permissive validator that accepts any client certificate, so "trust" there is
# a setting nobody enforces.
#
# Microsoft's opc-plc without --autoaccept is a real OPC Foundation .NET stack
# with a real directory trust store: an unknown client certificate lands in
# pki/rejected and the session is refused. Mounting that store from the host lets
# a test provision trust the way an operator does — move the certificate into
# pki/trusted/certs — and watch the same connection succeed.
#
# Usage:
#   scripts/opcua_cert_harness.sh uv run --no-sync pytest tests/test_opcua_cert_trust_live.py -q -rs
set -euo pipefail

NAME="${IAIOPS_OPCUA_STRICT_NAME:-iaiops-opcplc-strict}"
# 14841, not 50010: Linux hands out 32768-60999 as EPHEMERAL source ports, so any
# outbound connection this job makes — a docker pull, a uv download, the TSDB
# clients — can be assigned 50010, and then `docker run -p 50010:50010` fails with
# "address already in use". It depends entirely on which port the kernel happened
# to hand out, which is why it took months to appear and appeared on a docs-only
# PR. Same shape as the BACnet address bug in #179: infrastructure that works
# until the environment picks the other number.
PORT="${IAIOPS_OPCUA_STRICT_PORT:-14841}"
IMAGE="${IAIOPS_OPCUA_IMAGE:-mcr.microsoft.com/iotedge/opc-plc:2.12.28}"

# Refuse an ephemeral port rather than binding it and failing intermittently on
# whoever happens to hold it. Read the range from the kernel — it is tunable, and
# assuming 32768-60999 would be its own version of this bug.
read -r EPHEMERAL_LOW _ < /proc/sys/net/ipv4/ip_local_port_range 2>/dev/null || EPHEMERAL_LOW=32768
if [ "$PORT" -ge "$EPHEMERAL_LOW" ]; then
  echo "Port $PORT is inside this kernel's ephemeral range (from $EPHEMERAL_LOW)." >&2
  echo "Any outbound connection can be holding it when docker publishes it, which" >&2
  echo "fails as 'address already in use' at random. Pick a port below $EPHEMERAL_LOW." >&2
  exit 1
fi
PKI="${IAIOPS_OPCUA_PKI:-$(mktemp -d)/pki}"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cleanup
mkdir -p "$PKI/trusted/certs" "$PKI/trusted/crl" "$PKI/rejected/certs" "$PKI/own"
# The store must be writable by the container's user: the server drops rejected
# certificates into it, and the test moves one across.
chmod -R 777 "$PKI"

# NO --autoaccept and NO --unsecuretransport: this server requires a secure
# channel AND checks the client certificate against its trust store.
docker run -d --rm --name "$NAME" -p "$PORT:$PORT" -v "$PKI:/app/pki" "$IMAGE" --pn="$PORT" >/dev/null

for i in $(seq 1 60); do
  if docker logs "$NAME" 2>&1 | grep -q "PLC simulation started" \
     && (echo > "/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    echo "strict opc-plc ready on $PORT (attempt $i), pki=$PKI"
    break
  fi
  sleep 2
  if [ "$i" -eq 60 ]; then
    echo "strict opc-plc never became ready" >&2
    docker logs "$NAME" 2>&1 | tail -20 >&2
    exit 1
  fi
done

# Promotion has to happen INSIDE the container. Writing the same file from the
# host over a macOS bind mount does not take effect — the .NET directory store
# never sees it (measured: a host-side move leaves the session refused for 30s+,
# the identical copy made by `docker exec` is honoured immediately). Reading the
# store from the host works fine, which is why the mount stays: a test can watch
# the rejected certificate appear.
TRUST_SCRIPT="$(dirname "$PKI")/trust.sh"
cat > "$TRUST_SCRIPT" <<TRUST
#!/usr/bin/env bash
# Promote every certificate the server rejected into its trusted store.
set -euo pipefail
docker exec "$NAME" sh -c 'mkdir -p pki/trusted/certs && cp pki/rejected/certs/*.der pki/trusted/certs/'
TRUST
chmod +x "$TRUST_SCRIPT"

export IAIOPS_OPCUA_STRICT_URL="opc.tcp://127.0.0.1:$PORT"
export IAIOPS_OPCUA_PKI="$PKI"
export IAIOPS_OPCUA_TRUST_CMD="$TRUST_SCRIPT"
echo "IAIOPS_OPCUA_STRICT_URL=$IAIOPS_OPCUA_STRICT_URL"
echo "IAIOPS_OPCUA_PKI=$IAIOPS_OPCUA_PKI"
echo "IAIOPS_OPCUA_TRUST_CMD=$IAIOPS_OPCUA_TRUST_CMD"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <command…>" >&2
  exit 2
fi
"$@"
