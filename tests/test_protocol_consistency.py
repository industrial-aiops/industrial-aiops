"""Cross-registry protocol consistency — the meta-test that would have caught the
``secsgem`` regression (registered in the connector / overview / MCP modules but
missing from ``SUPPORTED_PROTOCOLS``).

A protocol in this monorepo is wired through SEVERAL independent places:
  - ``mcp_server.profiles.PROTOCOL_MODULES`` — the canonical protocol→tool-module map
  - ``iaiops/connectors/<key>/ops.py``       — the connector implementation
  - ``mcp_server/tools/<module>.py``          — the MCP tool module
  - ``iaiops.core.runtime.config.SUPPORTED_PROTOCOLS`` — config validation
  - ``iaiops.core.brain.overview.PROTOCOLS``  — the self-describing catalog
  - ``mcp_server.profiles.NAMED_PROFILES``    — edition/profile menus

Drift between any two is a latent bug (a tool that won't register, a config that
rejects a valid endpoint, a catalog that lies). These assertions pin them together.
"""

from __future__ import annotations

from pathlib import Path

from iaiops.core.brain.overview import PROTOCOLS as OVERVIEW_PROTOCOLS
from iaiops.core.runtime.config import SUPPORTED_PROTOCOLS
from mcp_server.profiles import NAMED_PROFILES, PROTOCOL_MODULES

# Canonical protocol key (connector-dir / PROTOCOL_MODULES key) → the alias name
# used in SUPPORTED_PROTOCOLS / overview, where it differs from the key.
ALIASES = {"eip": "ethernetip", "sparkplug": "mqtt"}

_REPO = Path(__file__).resolve().parent.parent
CANONICAL = set(PROTOCOL_MODULES)


def _in(key: str, collection) -> bool:
    """True if the canonical key (or its alias) is present in ``collection``."""
    return key in collection or ALIASES.get(key) in collection


def test_every_protocol_has_a_connector_and_tool_module() -> None:
    for key, module in PROTOCOL_MODULES.items():
        ops = _REPO / "iaiops" / "connectors" / key / "ops.py"
        assert ops.exists(), f"protocol {key!r}: missing connector {ops.relative_to(_REPO)}"
        tool = _REPO / "mcp_server" / "tools" / f"{module}.py"
        assert tool.exists(), f"protocol {key!r}: missing MCP module {tool.relative_to(_REPO)}"


def test_every_protocol_is_in_supported_protocols() -> None:
    missing = [k for k in CANONICAL if not _in(k, SUPPORTED_PROTOCOLS)]
    assert not missing, f"protocols missing from SUPPORTED_PROTOCOLS: {missing}"


def test_every_protocol_is_in_overview_catalog() -> None:
    overview_keys = {p["protocol"] for p in OVERVIEW_PROTOCOLS}
    missing = [k for k in CANONICAL if not _in(k, overview_keys)]
    assert not missing, f"protocols missing from overview.PROTOCOLS: {missing}"


def test_overview_catalog_has_no_unknown_protocols() -> None:
    """Every catalog entry must map back to a real connector key (no phantom rows)."""
    known = CANONICAL | set(ALIASES.values())
    unknown = [p["protocol"] for p in OVERVIEW_PROTOCOLS if p["protocol"] not in known]
    assert not unknown, f"overview lists protocols with no connector: {unknown}"


def test_named_profiles_reference_only_real_protocols() -> None:
    for profile, keys in NAMED_PROFILES.items():
        bad = [k for k in keys if k not in PROTOCOL_MODULES]
        assert not bad, f"profile {profile!r} references unknown protocols: {bad}"


def test_supported_protocols_are_all_wired() -> None:
    """Every SUPPORTED_PROTOCOLS entry maps to a canonical key (no orphan config)."""
    key_names = CANONICAL | {ALIASES[k] for k in ALIASES}
    orphans = [p for p in SUPPORTED_PROTOCOLS if p not in key_names]
    assert not orphans, f"SUPPORTED_PROTOCOLS has entries with no connector: {orphans}"
