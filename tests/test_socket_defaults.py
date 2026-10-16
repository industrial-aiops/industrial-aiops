"""The shipped socket deployments must admit the caller they are shipped for.

Verified on Docker 27.5 (2026-10-16): with `ports: 127.0.0.1:8000:8000` the server
sees a host caller as the bridge gateway (172.17.0.1), not 127.0.0.1 — so the
shipped default `IAIOPS_ALLOWLIST_IPS=127.0.0.1/32` answered 403 to every
legitimate request, correct bearer token included. Containers on a user network
(Siemens IE, compose networks) arrive from their own addresses, which a loopback
allowlist refuses just the same.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SOCKET_DEPLOYMENTS = (
    "deploy/margo/package.compose.yaml",
    "deploy/margo/compose.yaml",
    "deploy/airgap/compose.yaml",
    "deploy/siemens-ie/docker-compose.yaml",
)


def _default(value: str) -> str:
    """Resolve a compose `${VAR:-default}` to its default ('' when none)."""
    match = re.fullmatch(r"\$\{[A-Z_]+:-([^}]*)\}", str(value).strip())
    return match.group(1) if match else str(value)


def _iaiops_env(path: str) -> dict:
    services = yaml.safe_load((REPO / path).read_text(encoding="utf-8"))["services"]
    return next(s for name, s in services.items() if "iaiops" in name)["environment"]


@pytest.mark.parametrize("path", SOCKET_DEPLOYMENTS)
def test_no_shipped_default_allowlist_is_loopback_only(path):
    env = _iaiops_env(path)
    default = _default(env.get("IAIOPS_ALLOWLIST_IPS", ""))
    nets = [ipaddress.ip_network(n.strip()) for n in default.split(",") if n.strip()]
    assert not (nets and all(n.is_loopback for n in nets)), (
        f"{path} defaults IAIOPS_ALLOWLIST_IPS to {default!r}: behind a port mapping the "
        "caller is the bridge gateway, so this refuses everyone"
    )


def test_the_margo_descriptor_default_matches():
    descriptor = yaml.safe_load((REPO / "deploy/margo/margo.yaml").read_text(encoding="utf-8"))
    assert descriptor["parameters"]["allowlistIps"]["value"] == ""


def test_a_loopback_only_allowlist_on_a_wide_bind_is_warned_about(caplog):
    from iaiops.core.governance.allowlist import parse_allowlist
    from mcp_server.transport import warn_on_unreachable_allowlist

    with caplog.at_level(logging.WARNING):
        warn_on_unreachable_allowlist("0.0.0.0", parse_allowlist(None, ["127.0.0.1/32"]))
    assert "bridge gateway" in caplog.text


@pytest.mark.parametrize(
    ("host", "nets"),
    [("127.0.0.1", ["127.0.0.1/32"]), ("0.0.0.0", ["10.0.0.0/24"]), ("0.0.0.0", [])],
)
def test_no_warning_when_the_allowlist_can_match(caplog, host, nets):
    from iaiops.core.governance.allowlist import parse_allowlist
    from mcp_server.transport import warn_on_unreachable_allowlist

    with caplog.at_level(logging.WARNING):
        warn_on_unreachable_allowlist(host, parse_allowlist(None, nets or None))
    assert "bridge gateway" not in caplog.text
