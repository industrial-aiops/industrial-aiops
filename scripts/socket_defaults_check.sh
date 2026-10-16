#!/usr/bin/env bash
#
# Do the SHIPPED socket defaults admit a caller on the host?
#
# deploy/margo/package.compose.yaml publishes the MCP port as 127.0.0.1:8000:8000.
# Behind that mapping the server sees a host caller as the bridge gateway
# (e.g. 172.17.0.1), never 127.0.0.1 — so the old default
# IAIOPS_ALLOWLIST_IPS=127.0.0.1/32 answered 403 to every legitimate request
# (verified on Docker 27.5, 2026-10-16). Nothing caught it because no test ever
# called the container through its port mapping. This does, with the allowlist
# default read from the compose file itself, so the check follows the file.
#
# Usage:  scripts/socket_defaults_check.sh <image>
set -euo pipefail

IMAGE="${1:?usage: $0 <image>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose="${repo_root}/deploy/margo/package.compose.yaml"
name="iaiops-socket-check-$$"
port=18765

cleanup() { docker rm -f "${name}" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

# `IAIOPS_ALLOWLIST_IPS: ${IAIOPS_ALLOWLIST_IPS:-<default>}` → <default>
allowlist_default="$(sed -n 's/^ *IAIOPS_ALLOWLIST_IPS: *\${IAIOPS_ALLOWLIST_IPS:-\([^}]*\)}.*/\1/p' "${compose}")"
echo "package.compose.yaml allowlist default: '${allowlist_default}'"
token="$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/' | head -c 48)"

docker run -d --name "${name}" --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges:true --user 10001:10001 \
  -p "127.0.0.1:${port}:8000" \
  -e IAIOPS_MCP=modbus -e IAIOPS_MCP_TRANSPORT=streamable-http \
  -e IAIOPS_MCP_HOST=0.0.0.0 -e IAIOPS_MCP_PORT=8000 \
  -e IAIOPS_MCP_TOKEN="${token}" -e IAIOPS_MASTER_PASSWORD=socket-check-only \
  -e IAIOPS_ALLOWLIST_IPS="${allowlist_default}" \
  "${IMAGE}" >/dev/null

for _ in $(seq 1 30); do
  curl -s -o /dev/null "http://127.0.0.1:${port}/" && break
  sleep 1
done

code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${port}/mcp" \
  -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"socket-check","version":"1"}}}')"

if [ "${code}" != "200" ]; then
  echo "server log:"; docker logs "${name}" 2>&1 | tail -20
  printf '\n\033[31mFAIL\033[0m a host caller with a valid token got HTTP %s through the shipped port mapping.\n' "${code}" >&2
  exit 1
fi
printf '\033[32mPASS\033[0m the shipped socket defaults admit a host caller (HTTP 200).\n'
