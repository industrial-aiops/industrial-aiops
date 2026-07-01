"""Energy-edition extraction-readiness guard (spin-out prep — docs/ENERGY-SPINOUT.md).

The energy edition (IEC 60870-5-104 / DNP3 / IEC 61850) is slated to move into its
own repo. That is only clean if the energy connectors depend on the shared
``iaiops.core`` and *nothing else in iaiops* — in particular NOT on sibling
connectors (opcua/modbus/s7/…), which would stay behind.

This test statically parses the energy connector sources (no driver imports — the
energy libs are linux-only / no-wheel and absent from CI) and asserts every
``iaiops.*`` import resolves to ``iaiops.core`` or the connector's own package.
It is the machine-checkable precondition for the spin-out.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import iaiops.connectors as _connectors_pkg

_CONNECTORS_DIR = Path(_connectors_pkg.__file__).parent
_ENERGY = ("iec104", "dnp3", "iec61850")
# Sibling connectors that must NOT be reachable from the energy edition.
_SIBLINGS = (
    "opcua", "modbus", "s7", "mc", "eip", "mtconnect",
    "sparkplug", "ethercat", "secsgem", "profinet", "bacnet", "hart",
)


def _iaiops_imports(py_file: Path) -> list[str]:
    """Return every dotted ``iaiops.*`` module referenced by import statements."""
    tree = ast.parse(py_file.read_text("utf-8"), filename=str(py_file))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names if a.name.startswith("iaiops")]
        elif isinstance(node, ast.ImportFrom):
            # level==0 → absolute; energy connectors use absolute iaiops.* imports.
            if node.module and node.module.startswith("iaiops"):
                mods.append(node.module)
    return mods


@pytest.mark.unit
@pytest.mark.parametrize("connector", _ENERGY)
def test_energy_connector_depends_only_on_core(connector):
    pkg_dir = _CONNECTORS_DIR / connector
    assert pkg_dir.is_dir(), f"energy connector {connector} missing"
    own_prefix = f"iaiops.connectors.{connector}"
    for py_file in sorted(pkg_dir.glob("*.py")):
        for mod in _iaiops_imports(py_file):
            ok = (
                mod.startswith("iaiops.core")
                or mod == own_prefix
                or mod.startswith(own_prefix + ".")
            )
            assert ok, (
                f"{py_file.name} imports '{mod}' — energy edition must depend only on "
                f"iaiops.core (or its own package) to be extractable; got a non-core dep."
            )


@pytest.mark.unit
@pytest.mark.parametrize("connector", _ENERGY)
def test_energy_connector_imports_no_sibling(connector):
    pkg_dir = _CONNECTORS_DIR / connector
    banned = {f"iaiops.connectors.{s}" for s in _SIBLINGS}
    for py_file in sorted(pkg_dir.glob("*.py")):
        for mod in _iaiops_imports(py_file):
            root = ".".join(mod.split(".")[:3])  # iaiops.connectors.<name>
            assert root not in banned, (
                f"{py_file.name} imports sibling connector '{mod}' — would break the "
                f"energy spin-out (sibling stays behind)."
            )
