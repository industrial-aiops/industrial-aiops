"""Every caller-supplied output path goes through the same traversal guard.

WHY THIS FILE EXISTS
--------------------
Three tools take an ``out_path`` from the caller and write a file to it. Two of
them (``compliance_report``, the evidence zip export) validate it with
``iaiops.core.governance.evidence.validate_output_path``; one
(``alarm_rationalization_worksheet``) did not — it checked only that the parent
directory existed and then wrote wherever it was told.

Under this repo's own threat model that gap matters. The caller is a weak,
local, or prompt-injected model, and ``out_path`` is free text it chooses — the
same reasoning that put ``rca_narrate`` behind the no-egress gate because its
``base_url`` is caller-chosen. An unvalidated write path lets a confused model
overwrite a config file or a dotfile with CSV. The guard already existed; it was
simply not applied.

The gate below is generic: it finds every MCP tool taking an ``out_path``
parameter and asserts each one routes through the shared validator, so the NEXT
file-writing tool is caught by the suite rather than by a reviewer noticing.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "mcp_server" / "tools"

#: Names that count as routing through the shared guard.
VALIDATORS = frozenset({"validate_output_path", "_validate_output_path"})

#: ``module::function`` exemptions, each needing a written justification.
#: An exemption is a decision that should be argued for in review, and each one
#: here is corroborated by ``test_delegated_validation_still_happens`` — so a
#: refactor that removes the guard from the delegate turns this file red rather
#: than leaving a stale exemption pointing at nothing.
ALLOWLIST: dict[str, str] = {
    "mcp_server/tools/compliance_tools.py::compliance_evidence_bundle": (
        "Delegates the whole path to iaiops.core.governance.evidence."
        "export_evidence_bundle, which calls validate_output_path(suffixes=('.zip',)) "
        "itself. The scan reads one function body, so it cannot see one hop down."
    ),
}

#: ``allowlisted tool -> (module that must validate, expected suffix)``.
DELEGATED_VALIDATION: dict[str, tuple[str, str]] = {
    "mcp_server/tools/compliance_tools.py::compliance_evidence_bundle": (
        "iaiops/core/governance/evidence.py",
        ".zip",
    ),
}


def _tool_functions_taking_out_path() -> list[tuple[str, ast.FunctionDef]]:
    found: list[tuple[str, ast.FunctionDef]] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            names = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            if "out_path" in names:
                found.append((f"mcp_server/tools/{path.name}::{node.name}", node))
    return found


def _calls_a_validator(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in VALIDATORS:
                return True
    return False


def test_gate_finds_the_out_path_tools() -> None:
    """Guard the guard: a path/rename bug must not make this pass vacuously."""
    found = _tool_functions_taking_out_path()
    assert len(found) >= 2, f"expected the out_path-taking tools, found {found}"


def test_every_out_path_is_validated() -> None:
    """The primary gate — no tool writes to a caller-supplied path unchecked."""
    offenders = [
        qualified
        for qualified, fn in _tool_functions_taking_out_path()
        if qualified not in ALLOWLIST and not _calls_a_validator(fn)
    ]
    assert not offenders, (
        "these tools accept a caller-supplied out_path without routing it through "
        f"{sorted(VALIDATORS)} — a weak or prompt-injected model chooses this "
        f"argument: {offenders}"
    )


def test_delegated_validation_still_happens() -> None:
    """Corroborate every allowlist entry against the delegate's real source.

    An exemption that says "the layer below validates" is only as good as that
    layer. Checking it here means a refactor which moves the guard out of the
    delegate fails this file instead of silently widening the exemption.
    """
    assert set(ALLOWLIST) == set(DELEGATED_VALIDATION), (
        "every allowlist entry needs a DELEGATED_VALIDATION row proving the claim"
    )
    for tool, (module, suffix) in DELEGATED_VALIDATION.items():
        source = (REPO_ROOT / module).read_text(encoding="utf-8")
        assert "validate_output_path(" in source, (
            f"{tool} is exempted because {module} validates, but that module no "
            "longer calls validate_output_path"
        )
        assert suffix in source, (
            f"{tool} is exempted expecting {module} to enforce '{suffix}', "
            "which no longer appears there"
        )


def test_the_validator_actually_rejects_traversal(tmp_path: pathlib.Path) -> None:
    """The shared guard must reject '..' rather than merely normalising it."""
    from iaiops.core.governance.evidence import validate_output_path

    with pytest.raises(ValueError, match="traversal"):
        validate_output_path(tmp_path / ".." / "escaped.csv", suffixes=(".csv",))


def test_worksheet_rejects_a_traversal_path(tmp_path: pathlib.Path) -> None:
    """End-to-end: the tool that was missing the guard now refuses traversal."""
    from mcp_server.tools import alarm_tools

    events = [{"ts": "2026-07-19T00:00:00Z", "tag": "A", "state": "ACTIVE"}]
    result = alarm_tools.alarm_rationalization_worksheet(
        events=events, out_path=str(tmp_path / ".." / "escaped.csv")
    )
    assert "error" in result, f"traversal path was accepted: {result}"
    assert not (tmp_path.parent / "escaped.csv").exists()


def test_worksheet_rejects_a_non_csv_suffix(tmp_path: pathlib.Path) -> None:
    """The parameter is documented as a CSV destination; hold it to that."""
    from mcp_server.tools import alarm_tools

    events = [{"ts": "2026-07-19T00:00:00Z", "tag": "A", "state": "ACTIVE"}]
    result = alarm_tools.alarm_rationalization_worksheet(
        events=events, out_path=str(tmp_path / "worksheet.txt")
    )
    assert "error" in result, f"non-CSV suffix was accepted: {result}"


def test_worksheet_still_writes_a_valid_csv(tmp_path: pathlib.Path) -> None:
    """The guard must not break the working path it protects."""
    from mcp_server.tools import alarm_tools

    events = [{"ts": "2026-07-19T00:00:00Z", "tag": "A", "state": "ACTIVE"}]
    target = tmp_path / "worksheet.csv"
    result = alarm_tools.alarm_rationalization_worksheet(events=events, out_path=str(target))
    assert "error" not in result, result
    assert target.exists() and target.read_text(encoding="utf-8").strip()
