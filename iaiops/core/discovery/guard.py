"""The no-write guard — makes "this cannot change your plant" checkable.

The safety claim this product rests on is not "we are careful with writes"; it
is **"the discovery path contains no write code."** A promise is worth what its
enforcement is worth, so this module reads the discovery package's own source
and fails if a write ever becomes reachable from it.

Two independent checks, because they catch different mistakes:

* **Symbol check** — no connector write function is named anywhere in the
  package. This catches the obvious `from ...ops import s7_write_db`.
* **Import check** — no connector ``ops`` module is imported at module scope.
  Those modules mix reads and writes in one file (``s7/ops.py`` has the write at
  line 184 among reads), so importing one at import time puts a write one
  attribute lookup away. Identify calls must import lazily inside the function
  that makes them, which is also the convention the rest of the repo follows.

The guard is a library function rather than only a test so the appliance build
can run it against a packaged artifact, where a bad merge would otherwise ship.

This module names the forbidden functions as data and therefore excludes itself
from the scan — the one exclusion, asserted by the test.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Connector functions that put a change on the plant. Kept in sync with the
#: MCP-side manifest in ``tests/test_write_approval_contract.py``; the guard test
#: asserts this set covers it, so a new write tool cannot appear upstream
#: without this list noticing.
FORBIDDEN_WRITE_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "s7_write_db",
        "mc_write_words",
        "fins_write_words",
        "eip_write_tag",
        "ethercat_write_sdo",
        "ethercat_set_state",
        "profinet_dcp_set",
        "bacnet_write_property",
        "mqtt_publish",
        # The BAS supervisory write really is named just ``command``
        # (``iaiops/connectors/bas/ops.py``). See _AMBIGUOUS_SYMBOLS.
        "command",
    }
)

#: Writes whose names are too generic for a bare-identifier scan — a local
#: variable called ``command`` is not a plant write, and flagging it would train
#: reviewers to ignore this guard. These are caught by the *import* check
#: instead, which is exact: only ``from iaiops.connectors...ops import command``
#: is a finding.
_AMBIGUOUS_SYMBOLS: Final[frozenset[str]] = frozenset({"command"})

#: Plausible future write functions that do not exist upstream yet (the Modbus
#: and OPC-UA connectors are read-only today). Forbidding them now costs nothing
#: and closes the case where a write lands in a connector without also being
#: registered as an MCP tool, which is the only case the sync test would miss.
FORBIDDEN_IF_ADDED: Final[frozenset[str]] = frozenset(
    {
        "modbus_write_register",
        "modbus_write_registers",
        "modbus_write_coil",
        "opcua_write",
        "opcua_write_value",
        "hart_write",
        "iolink_write",
        "secsgem_send",
    }
)

#: Modules that must never be imported at module scope from the discovery
#: package (they contain writes alongside reads).
FORBIDDEN_MODULE_PREFIXES: Final[tuple[str, ...]] = (
    "iaiops.connectors.",
    "mcp_server",
)

#: The only file exempt from the symbol scan — this one, which must name the
#: forbidden symbols in order to forbid them.
_SELF: Final = "guard.py"


@dataclass(frozen=True)
class GuardFinding:
    file: str
    line: int
    kind: str  # "write_symbol" | "write_import" | "eager_connector_import"
    detail: str


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def _module_level_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Imports at module scope only — a lazy import inside a function is fine."""
    found: list[tuple[int, str]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
    return found


def audit_source(root: Path | None = None) -> tuple[GuardFinding, ...]:
    """Scan the discovery package. An empty result is the guarantee."""
    root = root or _package_root()
    findings: list[GuardFinding] = []

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for lineno, module in _module_level_imports(tree):
            if module.startswith(FORBIDDEN_MODULE_PREFIXES):
                findings.append(
                    GuardFinding(
                        file=path.name,
                        line=lineno,
                        kind="eager_connector_import",
                        detail=(
                            f"{module} is imported at module scope. Connector ops "
                            "modules hold writes beside reads; import inside the "
                            "function that needs the read instead."
                        ),
                    )
                )

        if path.name == _SELF:
            continue

        forbidden_all = FORBIDDEN_WRITE_SYMBOLS | FORBIDDEN_IF_ADDED

        # Exact check: importing a write BY NAME from a connector, at any scope.
        # This is what catches the generically-named ones (`command`) without
        # false-flagging an ordinary local variable of the same name.
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith(FORBIDDEN_MODULE_PREFIXES):
                continue
            for alias in node.names:
                if alias.name in forbidden_all:
                    findings.append(
                        GuardFinding(
                            file=path.name,
                            line=node.lineno,
                            kind="write_import",
                            detail=(
                                f"imports {alias.name!r} from {node.module} — that is a "
                                "plant write. The discovery path must contain no write "
                                "code at all: not disabled, absent."
                            ),
                        )
                    )

        # Broad check: the unambiguous write names must not appear at all, even
        # as an attribute call on a lazily-imported module (``ops.s7_write_db``).
        unambiguous = forbidden_all - _AMBIGUOUS_SYMBOLS
        for node in ast.walk(tree):
            name = (
                node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else node.name
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                else None
            )
            if name and name in unambiguous:
                findings.append(
                    GuardFinding(
                        file=path.name,
                        line=getattr(node, "lineno", 0),
                        kind="write_symbol",
                        detail=(
                            f"{name!r} is a plant write. The discovery path must "
                            "contain no write code at all — not disabled, absent."
                        ),
                    )
                )

    return tuple(findings)


def assert_no_write_path(root: Path | None = None) -> None:
    """Raise if any write became reachable. Called by the guard test and by the
    appliance build before an artifact is allowed to ship."""
    findings = audit_source(root)
    if findings:
        lines = "\n".join(f"  {f.file}:{f.line} [{f.kind}] {f.detail}" for f in findings)
        raise AssertionError("The discovery package must contain no write path. Found:\n" + lines)


__all__ = [
    "FORBIDDEN_WRITE_SYMBOLS",
    "FORBIDDEN_IF_ADDED",
    "FORBIDDEN_MODULE_PREFIXES",
    "GuardFinding",
    "audit_source",
    "assert_no_write_path",
]
