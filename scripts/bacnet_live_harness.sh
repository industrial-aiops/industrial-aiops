#!/usr/bin/env bash
# Reproducible harness for tests/test_bacnet_live.py.
#
# BACnet/IP discovery is a UDP broadcast, and loopback does not carry it, so the
# virtual device and the connector must sit on two addresses of one real subnet.
# The test starts BOTH in one process, so this cannot be split across two hosts —
# it needs two IPs on a single interface.
#
# This file exists because the 2026-07-02 verification ("two-IP subnet in a Linux
# container", docs/PREVIEW-VERIFICATION.md) never recorded its recipe. A claim of
# "verified" that cannot be re-run is not a claim anyone can check later.
#
# Usage (Linux, needs CAP_NET_ADMIN to add the second address):
#   sudo scripts/bacnet_live_harness.sh
set -euo pipefail

IFACE="${IAIOPS_BACNET_IFACE:-}"
if [ -z "$IFACE" ]; then
  IFACE="$(ip -4 route show default | awk '{print $5; exit}')"
fi
BASE="$(ip -4 -o addr show dev "$IFACE" | awk '{print $4; exit}')"
PRIMARY="${BASE%%/*}"
MASK="${BASE##*/}"
# Pick the second address by 32-bit arithmetic, not by incrementing the last
# octet. A runner whose primary address ends in .255 is perfectly ordinary on a
# /20 — the broadcast there is 10.1.15.255, not 10.1.0.255 — and the naive
# version produced "10.1.0.256", which is not an address at all. Intermittent by
# nature: it depended entirely on which IP the runner happened to be given.
ip_to_int() {
  local IFS=. ; read -r a b c d <<< "$1" ; echo $(( (a<<24) + (b<<16) + (c<<8) + d ))
}
int_to_ip() {
  echo "$(( ($1>>24) & 255 )).$(( ($1>>16) & 255 )).$(( ($1>>8) & 255 )).$(( $1 & 255 ))"
}

PRIMARY_INT="$(ip_to_int "$PRIMARY")"
HOST_BITS=$(( 32 - MASK ))
NET_INT=$(( PRIMARY_INT & ~((1 << HOST_BITS) - 1) & 0xFFFFFFFF ))
BCAST_INT=$(( NET_INT | ((1 << HOST_BITS) - 1) ))

# Step away from the primary, staying inside the subnet and off both the network
# and broadcast addresses. Going up unless that would hit broadcast, in which
# case go down — a /31 has nowhere to go and is rejected rather than fudged.
SECOND_INT=$(( PRIMARY_INT + 1 ))
if [ "$SECOND_INT" -ge "$BCAST_INT" ]; then
  SECOND_INT=$(( PRIMARY_INT - 1 ))
fi
if [ "$SECOND_INT" -le "$NET_INT" ] || [ "$SECOND_INT" -ge "$BCAST_INT" ]; then
  echo "No usable second address beside $PRIMARY/$MASK — the subnet is too small" >&2
  exit 1
fi
SECOND="$(int_to_ip "$SECOND_INT")"

echo "interface=$IFACE primary=$PRIMARY/$MASK second=$SECOND/$MASK"

if ! ip -4 -o addr show dev "$IFACE" | grep -q "$SECOND/"; then
  ip addr add "$SECOND/$MASK" dev "$IFACE"
  echo "added $SECOND/$MASK to $IFACE"
fi

export IAIOPS_BACNET_CLIENT_IP="$PRIMARY/$MASK"
export IAIOPS_BACNET_DEVICE_IP="$SECOND/$MASK"
echo "IAIOPS_BACNET_CLIENT_IP=$IAIOPS_BACNET_CLIENT_IP"
echo "IAIOPS_BACNET_DEVICE_IP=$IAIOPS_BACNET_DEVICE_IP"

exec "${@:-python -m pytest tests/test_bacnet_live.py -q -rs}"
