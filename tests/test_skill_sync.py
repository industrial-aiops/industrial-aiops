"""SKILL.md ↔ MCP tool-registry sync guards (router + edition skills).

Layer-3 layout: ``skills/iaiops/SKILL.md`` is a thin ROUTER (no tool tables);
each ``skills/iaiops-<edition>/SKILL.md`` carries that edition's tool list and
support matrix. These tests keep the whole skill set from drifting behind the
actual tool surface:

a) every ``@mcp.tool`` name is documented in at least one edition skill;
b) each edition skill only names tools its declared ``IAIOPS_MCP`` profile(s)
   actually expose (brain tools are always exposed);
c) every version pin quoted in a skill support matrix matches pyproject.toml;
d) the write-tool count claimed in the router matches the ``risk_level="high"``
   registrations.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mcp_server import profiles

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "mcp_server" / "tools"
ROUTER_SKILL = REPO_ROOT / "skills" / "iaiops" / "SKILL.md"
EDITION_SKILLS = sorted((REPO_ROOT / "skills").glob("iaiops-*/SKILL.md"))

# @mcp.tool() possibly followed by more decorators, then the def line.
_TOOL_DEF_RE = re.compile(r"@mcp\.tool\(\)(?:\n@[^\n]+)*\ndef ([A-Za-z_][A-Za-z0-9_]*)")
_HIGH_RISK_RE = re.compile(
    r'@mcp\.tool\(\)\n@governed_tool\(risk_level="high"[^)]*\)(?:\n@[^\n]+)*\ndef (\w+)'
)
_MCP_SPEC_RE = re.compile(r"IAIOPS_MCP=([a-z0-9_,]+)")
_BACKTICK_RE = re.compile(r"`([^`\s]+)`")
# e.g. `asyncua>=1.0,<2` / `pyserial>=3.5` / `BAC0>=2023.6,<2026`
_PIN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*>=[0-9][0-9A-Za-z.,<>=!-]*$")


def _tools_per_module() -> dict[str, list[str]]:
    return {
        path.stem: _TOOL_DEF_RE.findall(path.read_text("utf-8"))
        for path in sorted(TOOLS_DIR.glob("*.py"))
    }


def _registered_tool_names() -> list[str]:
    return [name for names in _tools_per_module().values() for name in names]


def _skill_specs(text: str) -> list[str]:
    """All IAIOPS_MCP=<spec> strings mentioned in a skill body."""
    return _MCP_SPEC_RE.findall(text)


@pytest.mark.unit
def test_registry_is_nonempty_sanity():
    names = _registered_tool_names()
    assert len(names) >= 100, f"suspiciously few tools parsed: {len(names)}"
    assert len(EDITION_SKILLS) >= 5, (
        f"expected the edition skill set (fab/factory/process/building/water), "
        f"found only: {[p.parent.name for p in EDITION_SKILLS]}"
    )


@pytest.mark.unit
def test_every_registered_tool_documented_in_skill():
    """(a) Every @mcp.tool name appears in at least one edition skill."""
    union = "\n".join(p.read_text("utf-8") for p in EDITION_SKILLS)
    missing = [n for n in _registered_tool_names() if f"`{n}`" not in union]
    assert not missing, (
        f"No edition skill documents {len(missing)} registered tool(s): {missing}. "
        f"Add a one-line entry to the owning edition under skills/iaiops-<edition>/."
    )


@pytest.mark.unit
def test_router_has_no_per_tool_tables():
    """The router stays thin: it may cite the 8 MOC writes, nothing else."""
    router = ROUTER_SKILL.read_text("utf-8")
    high_risk = set(
        _HIGH_RISK_RE.findall(
            "\n".join(p.read_text("utf-8") for p in sorted(TOOLS_DIR.glob("*.py")))
        )
    )
    allowed = high_risk | {"protocols_supported"}  # capability-map pointer is fine
    cited = {n for n in _registered_tool_names() if f"`{n}`" in router}
    stray = sorted(cited - allowed)
    assert not stray, f"Router skill must not carry per-tool docs; move to an edition: {stray}"


@pytest.mark.parametrize("skill_path", EDITION_SKILLS, ids=lambda p: p.parent.name)
@pytest.mark.unit
def test_edition_skill_tools_subset_of_profile(skill_path: Path):
    """(b) Each edition skill's tools ⊆ tools its declared profile(s) expose."""
    text = skill_path.read_text("utf-8")
    specs = _skill_specs(text)
    assert specs, f"{skill_path} declares no IAIOPS_MCP=<profile> launch line"

    # Full module surface for the edition's launch spec(s): brain + any per-edition
    # EDITION_MODULES + the protocol modules — the single source of truth is
    # selected_tool_modules (so this never drifts as the mechanism grows).
    allowed_modules: set[str] = set()
    resolved_any = False
    for spec in specs:
        try:
            allowed_modules.update(profiles.selected_tool_modules(spec))
            resolved_any = True
        except profiles.UnknownProtocolError:
            continue  # e.g. a profile merged from another branch, not present here
    if not resolved_any:
        pytest.skip(f"none of {specs} resolvable in this checkout — profile pending merge")

    per_module = _tools_per_module()
    allowed = {name for module in allowed_modules for name in per_module.get(module, [])}

    registered = set(_registered_tool_names())
    cited = {tok for tok in _BACKTICK_RE.findall(text) if tok in registered}
    stray = sorted(cited - allowed)
    assert not stray, (
        f"{skill_path.parent.name} cites tools outside its IAIOPS_MCP={specs} surface: {stray}"
    )


@pytest.mark.parametrize("skill_path", EDITION_SKILLS, ids=lambda p: p.parent.name)
@pytest.mark.unit
def test_skill_version_pins_match_pyproject(skill_path: Path):
    """(c) Every pin quoted in a skill support matrix exists verbatim in pyproject."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text("utf-8")
    text = skill_path.read_text("utf-8")
    pins = [tok for tok in _BACKTICK_RE.findall(text) if _PIN_RE.match(tok)]
    assert pins, f"{skill_path.parent.name} quotes no version pins in its support matrix"
    stale = [pin for pin in pins if f'"{pin}"' not in pyproject]
    assert not stale, f"{skill_path.parent.name} quotes pin(s) not found in pyproject.toml: {stale}"


@pytest.mark.unit
def test_skill_write_tool_count_matches_registry():
    """(d) The 'N write tools' claim in the router matches the high-risk registry."""
    high_risk: list[str] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        high_risk.extend(_HIGH_RISK_RE.findall(path.read_text("utf-8")))
    router = ROUTER_SKILL.read_text("utf-8")
    claims = re.findall(r"The (\d+) write tools", router)
    assert claims, "Router SKILL.md no longer states the write-tool count"
    for claim in claims:
        assert int(claim) == len(high_risk), (
            f"Router claims {claim} write tools but the registry has "
            f"{len(high_risk)}: {sorted(high_risk)}"
        )
    # Every MOC write must also be named in the router's safety invariants.
    missing = [n for n in high_risk if f"`{n}`" not in router]
    assert not missing, f"Router safety section is missing MOC write tool(s): {missing}"
