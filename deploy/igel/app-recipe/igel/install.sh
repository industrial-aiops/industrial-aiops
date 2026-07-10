#!/bin/sh
# IGEL OS 12 app-recipe install hook (igelpkg). Enables the systemd unit that runs the neutral
# iaiops container via Podman. 待核实: exact hook API + service lifecycle vs the IGEL SDK Reference
# Manual. Not validated on a real IGEL OS 12 endpoint.
set -eu

# Enable the unit shipped in input/all/etc/systemd/system/iaiops.service
enable_system_service iaiops.service
