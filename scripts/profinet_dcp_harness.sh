#!/usr/bin/env bash
# Reproducible harness for tests/test_profinet_live.py.
#
# PROFINET-DCP is layer-2: no IP, no loopback, an Ethernet frame with ether-type
# 0x8892 sent to a multicast MAC. It therefore needs two real interfaces on one
# wire — which a veth pair is. pnio-dcp binds a raw socket on one end (selected by
# the IP it carries, hence the address below), tests/profinet_dcp_station.py
# answers on the other.
#
# This is why PROFINET stopped being mock-only: not because a PROFINET simulator
# appeared, but because the missing half was a responder rather than a device.
# An earlier note in docs/VERIFICATION-RECORD.md wrote it off as hardware-gated
# like EtherCAT; that was wrong, and this file is the recipe so it stays wrong.
#
# Needs CAP_NET_ADMIN (create the veth pair) and CAP_NET_RAW (the sockets):
#   sudo scripts/profinet_dcp_harness.sh uv run --no-sync pytest tests/test_profinet_live.py -q -rs
set -euo pipefail

CLIENT_IF="${IAIOPS_PROFINET_CLIENT_IF:-iaiops-pn0}"
DEVICE_IF="${IAIOPS_PROFINET_DEVICE_IF:-iaiops-pn1}"
# A /30 on a range no plant uses for PROFINET; the addresses only exist so
# pnio-dcp can pick the interface — DCP itself never looks at them.
CLIENT_IP="${IAIOPS_PROFINET_CLIENT_IP:-10.77.99.1}"
DEVICE_IP="10.77.99.2"

cleanup() {
  # Deleting either end removes the pair, so one delete is enough.
  ip link delete "$CLIENT_IF" 2>/dev/null || true
}

# The trap covers INT/TERM as well as EXIT, and is armed BEFORE anything is
# created: a run killed between `ip link add` and the addressing used to leave a
# half-built pair behind, which every later run then "reused" — printing a
# reassuring line and handing pnio-dcp an interface with no address, whose error
# ("could not find a network interface for ip …") names the wrong problem.
trap cleanup EXIT INT TERM

# Any leftover from a previous run is torn down rather than reused. Reuse saved
# nothing (a veth pair costs milliseconds) and could only ever hand this run a
# state it had not verified.
if ip link show "$CLIENT_IF" >/dev/null 2>&1 || ip link show "$DEVICE_IF" >/dev/null 2>&1; then
  echo "removing a leftover $CLIENT_IF/$DEVICE_IF from an earlier run"
  ip link delete "$CLIENT_IF" 2>/dev/null || ip link delete "$DEVICE_IF" 2>/dev/null || true
fi

ip link add "$CLIENT_IF" type veth peer name "$DEVICE_IF"
ip addr add "$CLIENT_IP/30" dev "$CLIENT_IF"
ip addr add "$DEVICE_IP/30" dev "$DEVICE_IF"
ip link set "$CLIENT_IF" up
ip link set "$DEVICE_IF" up
echo "created veth pair $CLIENT_IF ($CLIENT_IP) <-> $DEVICE_IF ($DEVICE_IP)"

export IAIOPS_PROFINET_CLIENT_IP="$CLIENT_IP"
export IAIOPS_PROFINET_DEVICE_IF="$DEVICE_IF"
echo "IAIOPS_PROFINET_CLIENT_IP=$IAIOPS_PROFINET_CLIENT_IP"
echo "IAIOPS_PROFINET_DEVICE_IF=$IAIOPS_PROFINET_DEVICE_IF"

# No default command. `sudo` resets PATH, so a bare `python -m pytest` would run
# the SYSTEM interpreter, where pnio-dcp is absent — the module-level skip fires
# and the script exits 0 having verified nothing. Make the caller say which
# interpreter, the way the CI step and the usage line above do.
if [ "$#" -eq 0 ]; then
  echo "usage: $0 <command…>   e.g. $0 uv run --no-sync pytest tests/test_profinet_live.py -q -rs" >&2
  exit 2
fi
"$@"
