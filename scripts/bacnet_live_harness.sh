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
SECOND="${PRIMARY%.*}.$(( ${PRIMARY##*.} + 1 ))"

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
