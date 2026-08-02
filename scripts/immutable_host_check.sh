#!/usr/bin/env bash
# Is the container image fit for an IMMUTABLE edge host?
#
# Margo's device role is a hardened, centrally-managed host (IGEL OS and friends).
# Validating on a specific one needs that vendor's OS; what an immutable host
# *demands of an application* does not — it is: run as a non-root user, tolerate a
# read-only root filesystem, and keep all mutable state inside the declared
# volume. That is checkable anywhere Docker runs, and it is what this script does.
#
# It exists because the published images failed it. `VOLUME` after `USER` left
# /home/iaiops/.iaiops owned by root and 0755, so the app could not write its own
# audit chain: reads ran unaudited and every high-risk write was denied
# fail-closed. The governance layer behaved correctly; the image did not.
#
# Usage:  scripts/immutable_host_check.sh <image>
set -euo pipefail

IMAGE="${1:?usage: $0 <image>}"
VOLUME="iaiops-immutable-check-$$"
cleanup() { docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

probe=$(cat <<'PY'
import os, pathlib, sys
from iaiops.core.governance.audit import get_engine

failures = []
home = pathlib.Path(os.environ["IAIOPS_HOME"])

if os.getuid() == 0:
    failures.append("runs as root")
if os.access("/usr", os.W_OK):
    failures.append("root filesystem is writable (not read-only-safe)")
if not os.access(home, os.W_OK):
    failures.append(f"IAIOPS_HOME {home} is NOT writable by uid {os.getuid()} — "
                    "reads go unaudited and every high-risk write is denied")
mode = oct(home.stat().st_mode)[-3:]
if mode != "700":
    failures.append(f"IAIOPS_HOME is mode {mode}, expected 700 (secrets + audit live there)")

# The real question, not a proxy for it: does the audit chain accept a row?
try:
    engine = get_engine()
    if not engine.healthy:  # a property, not a method
        failures.append("the audit engine reports unhealthy")
    else:
        engine.log(skill="immutable-host-check", tool="probe", status="ok")
except Exception as exc:  # noqa: BLE001 — any failure here is the finding
    failures.append(f"audit write raised {type(exc).__name__}: {exc}")

print("uid=%d rootfs_writable=%s home=%s mode=%s"
      % (os.getuid(), os.access("/usr", os.W_OK), home, mode))
if failures:
    print("IMMUTABLE-HOST CHECK FAILED:")
    for item in failures:
        print("  - " + item)
    sys.exit(1)
print("IMMUTABLE-HOST CHECK PASSED")
PY
)

echo "checking $IMAGE under read-only rootfs, non-root, no-new-privileges…"
docker run --rm \
  --read-only --tmpfs /tmp \
  --user 10001:10001 \
  --security-opt no-new-privileges \
  -v "$VOLUME:/home/iaiops/.iaiops" \
  --entrypoint python \
  "$IMAGE" -c "$probe"
