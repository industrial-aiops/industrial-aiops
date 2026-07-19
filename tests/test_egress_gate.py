"""Repo-wide CI gate: an MCP tool that can transmit data off-box must declare it.

The point of this file is that the NEXT egress tool is caught by the suite, not
by a reviewer noticing. ``IAIOPS_NO_EGRESS`` withholds tools by reading the
``@governed_tool(egress=True)`` flag, so an egress tool that never got the flag
is a silent hole in the guarantee — exactly the failure mode a hand-maintained
name list would produce.

It is a static (AST) scan of ``iaiops/`` and ``mcp_server/`` — it never imports
or calls anything, so it needs no devices and adds no runtime cost.

WHAT COUNTS AS EGRESS HERE
--------------------------
Egress = the tool's purpose is to transmit local/plant data to a destination the
CALLER names. Deliberately excluded, because conflating them would make the gate
meaningless:

* **Protocol writes to a plant device** (OPC-UA write, BACnet setpoint, an HTTP
  PUT to a BAS controller). Data does go out on a wire, but to the equipment
  under the operator's own control. That is a *write*, and ``IAIOPS_READ_ONLY``
  is the gate for it — see ``mcp_server/readonly.py``.
* **Reads that open an outbound connection** (an MQTT SUBSCRIBE, a TSDB query,
  an MTConnect poll). The payload flows IN. iaiops is a network tap; if opening
  a socket were egress, the gate would have to withhold everything.
* **Local file writes** (``export_data``, ``compliance_evidence_bundle``). The
  bytes stay on the box.

SEE ALSO: ``tests/test_no_egress_gate.py`` proves the runtime behaviour of the
gate; this file proves nothing escaped the classification.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_PACKAGE = "iaiops"
TOOLS_DIR = "mcp_server/tools"

#: Attribute names that, when CALLED, put bytes on a socket. Deliberately a
#: small, high-signal set: these are the primitives every outbound path in this
#: repo bottoms out in. Used to DERIVE which ``iaiops`` functions transmit,
#: rather than trusting a list of them.
SEND_PRIMITIVES = frozenset({"post", "put", "publish", "send", "sendall", "sendto", "urlopen"})


class Facade(NamedTuple):
    """A declared multi-hop transport entry point.

    ``transport_root`` is the module tree that actually owns the socket, so the
    declaration can be checked against source rather than believed.
    """

    transport_root: str
    why: str


#: Module prefixes whose public callables exist to ship data to a caller-named
#: destination. Needed in addition to the derived scan above because these reach
#: their socket through two or more hops (facade → adapter → client lib), which
#: a static scan cannot follow — and because the TDengine / IoTDB adapters
#: transmit through client-library methods that are not send primitives at all
#: (``session.insert_*``, ``conn.execute``), so nothing would flag them.
EGRESS_FACADES: dict[str, Facade] = {
    "iaiops.core.egress": Facade(
        "iaiops.core.egress",
        "the message-bus publisher belt — get_publisher(...).publish_* puts "
        "already-read points / computed findings on an external NATS subject.",
    ),
    "iaiops.core.sink.push": Facade(
        "iaiops.core.sink",
        "historian_push writes collected telemetry into an external TSDB "
        "(TDengine / IoTDB / InfluxDB) at a caller-supplied host.",
    ),
    "iaiops.core.llm": Facade(
        "iaiops.core.llm",
        "the model SPI POSTs the prompt — which carries the RCA verdict and its "
        "plant evidence — to a caller-supplied base_url. The default is "
        "localhost, but the destination is a free-text argument, so under a "
        "'nothing leaves this box' promise the tool has to go.",
    ),
}

#: Qualified ``module::function`` names exempted from the gate, each with a
#: written justification. Empty on purpose — an exemption is a decision that
#: should have to be argued for in review, not a quiet default.
ALLOWLIST: dict[str, str] = {}


# ── source scanning ──────────────────────────────────────────────────────────


def _module_name(path: Path) -> str:
    dotted = path.relative_to(REPO_ROOT).with_suffix("").as_posix().replace("/", ".")
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


def _python_files(package: str) -> list[Path]:
    files = sorted((REPO_ROOT / package).rglob("*.py"))
    assert files, f"found no source files under {package}/ — the gate would pass vacuously"
    return files


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _is_send_call(node: ast.AST) -> bool:
    """True for a call that hands bytes to a transport (``x.post(...)``, ...)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in SEND_PRIMITIVES
    return isinstance(func, ast.Name) and func.id == "urlopen"


def _transmitting_functions() -> frozenset[str]:
    """Fully-qualified ``iaiops`` functions whose own body calls a send primitive.

    Fully qualified on purpose: bare names like ``send`` / ``write`` / ``execute``
    collide across the codebase, and a bare-name match would flag unrelated tools.
    """
    found: set[str] = set()
    for path in _python_files(SCANNED_PACKAGE):
        module = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for fn in _functions(tree):
            if any(_is_send_call(node) for node in ast.walk(fn)):
                found.add(f"{module}.{fn.name}")
    return frozenset(found)


def _import_sources(tree: ast.AST) -> dict[str, str]:
    """Map each locally-bound import name to the dotted path it came from."""
    sources: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                sources[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                sources[alias.asname or alias.name] = alias.name
    return sources


def _called_names(fn: ast.AST) -> set[tuple[str, str | None]]:
    """``(base, attr)`` pairs for every call in ``fn``: ``f()`` and ``m.f()``."""
    calls: set[tuple[str, str | None]] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            calls.add((func.id, None))
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            calls.add((func.value.id, func.attr))
    return calls


def _is_mcp_tool(fn: ast.AST) -> bool:
    for decorator in getattr(fn, "decorator_list", []):
        node = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(node, ast.Attribute) and node.attr == "tool":
            return True
    return False


def _declares_egress(fn: ast.AST) -> bool:
    """True if the function carries ``@governed_tool(..., egress=True)``."""
    for decorator in getattr(fn, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != "governed_tool":
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "egress":
                return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def _under_facade(source: str) -> bool:
    return any(source == f or source.startswith(f"{f}.") for f in EGRESS_FACADES)


def _reaches_transport(fn: ast.AST, imports: dict[str, str], transmitting: frozenset[str]) -> bool:
    """True if ``fn`` calls something imported from a transport facade or sender."""
    for base, attr in _called_names(fn):
        source = imports.get(base)
        if source is None:
            continue
        if _under_facade(source):
            return True
        qualified = f"{source}.{attr}" if attr else source
        if qualified in transmitting:
            return True
    return False


def _undeclared_egress_tools() -> list[str]:
    transmitting = _transmitting_functions()
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / TOOLS_DIR).glob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        imports = _import_sources(tree)
        for fn in _functions(tree):
            qualified = f"{rel}::{fn.name}"
            if qualified in ALLOWLIST or not _is_mcp_tool(fn):
                continue
            if _reaches_transport(fn, imports, transmitting) and not _declares_egress(fn):
                offenders.append(qualified)
    return offenders


# ── the gates ────────────────────────────────────────────────────────────────


def test_transport_reaching_tools_declare_egress() -> None:
    """Every MCP tool that reaches a transport must carry ``egress=True``.

    DOCUMENTED LIMITS — the strongest honest approximation a static scan can
    make, not a proof. It does NOT catch:

    * a NEW multi-hop transport facade (``iaiops/core/<something>/``) that no
      declared prefix covers and whose own module calls no send primitive. That
      is what ``test_declared_facades_still_transmit`` is for: it fails when a
      declared facade stops transmitting, which is the same refactor that would
      move the transport somewhere undeclared;
    * a tool that reaches a transport through a locally-defined helper rather
      than a direct call (the helper is a different function to the scan);
    * dynamic dispatch (``getattr(mod, name)()``, a registry lookup);
    * whether a tool marked ``egress=True`` really transmits. Over-declaring
      fails closed — it withholds a tool that did not need withholding — so it
      is not treated as an error here.
    """
    offenders = _undeclared_egress_tools()
    assert not offenders, (
        "these MCP tools reach an egress transport but do not declare "
        "@governed_tool(..., egress=True), so IAIOPS_NO_EGRESS would NOT "
        f"withhold them: {offenders}"
    )


def test_declared_facades_still_transmit() -> None:
    """Each declared facade must still contain a real send primitive somewhere.

    Guards against the quiet failure where a transport is refactored out of a
    declared module tree: the prefix would keep matching nothing, the gate would
    keep passing, and the actual transport would have moved somewhere undeclared.
    """
    transmitting = _transmitting_functions()
    for prefix, facade in EGRESS_FACADES.items():
        assert facade.why.strip(), f"{prefix} is declared without a justification"
        assert (REPO_ROOT / prefix.replace(".", "/")).exists() or (
            REPO_ROOT / f"{prefix.replace('.', '/')}.py"
        ).exists(), f"declared egress facade '{prefix}' does not exist — stale declaration"
        assert any(name.startswith(f"{facade.transport_root}.") for name in transmitting), (
            f"declared egress facade '{prefix}' has no function under "
            f"'{facade.transport_root}' that calls a send primitive — either the "
            "transport moved (declare its new home) or the facade is dead."
        )


def test_gate_actually_has_teeth() -> None:
    """Guard the guard: the predicates must fire on known-bad snippets.

    Without this, a refactor that broke the AST matching would leave the gate
    above passing vacuously forever.
    """
    bad = ast.parse(
        "from iaiops.core.egress import get_publisher\n"
        "@mcp.tool()\n"
        "@governed_tool(risk_level='low')\n"
        "def leaky(points):\n"
        "    return get_publisher('nats').publish_points(points)\n"
    )
    fn = next(_functions(bad))
    imports = _import_sources(bad)
    assert _is_mcp_tool(fn) is True
    assert _declares_egress(fn) is False
    assert _reaches_transport(fn, imports, frozenset()) is True

    good = ast.parse(
        "from iaiops.core.egress import get_publisher\n"
        "@mcp.tool()\n"
        "@governed_tool(risk_level='low', egress=True)\n"
        "def declared(points):\n"
        "    return get_publisher('nats').publish_points(points)\n"
    )
    assert _declares_egress(next(_functions(good))) is True

    # egress=False must NOT count as a declaration.
    off = ast.parse("@governed_tool(egress=False)\ndef t():\n    return {}\n")
    assert _declares_egress(next(_functions(off))) is False

    # A connector helper that itself publishes is reached by the DERIVED path,
    # with no facade prefix involved.
    derived = ast.parse(
        "from iaiops.connectors.sparkplug import ops\n"
        "@mcp.tool()\n"
        "@governed_tool(risk_level='high')\n"
        "def cmd(topic, payload):\n"
        "    return ops.mqtt_publish(topic, payload)\n"
    )
    fn = next(_functions(derived))
    transmitting = frozenset({"iaiops.connectors.sparkplug.ops.mqtt_publish"})
    assert _reaches_transport(fn, _import_sources(derived), transmitting) is True
    assert _reaches_transport(fn, _import_sources(derived), frozenset()) is False

    # A non-tool function is out of scope even if it reaches a transport.
    helper = ast.parse(
        "from iaiops.core.egress import get_publisher\n"
        "def _helper():\n"
        "    return get_publisher('nats')\n"
    )
    assert _is_mcp_tool(next(_functions(helper))) is False

    # A local file write is not a transport.
    local = ast.parse(
        "from iaiops.core.sink.export import export_samples\n"
        "@mcp.tool()\n"
        "@governed_tool(risk_level='low')\n"
        "def export_data(out):\n"
        "    return export_samples(out)\n"
    )
    fn = next(_functions(local))
    assert _reaches_transport(fn, _import_sources(local), _transmitting_functions()) is False


def test_gate_scans_a_real_and_non_trivial_surface() -> None:
    """The scan must actually cover the packages and find the known senders.

    A silent path/rename bug would otherwise make the gate above pass by
    scanning nothing.
    """
    assert len(_python_files(SCANNED_PACKAGE)) > 100
    tool_modules = sorted((REPO_ROOT / TOOLS_DIR).glob("*.py"))
    assert len(tool_modules) > 30, f"only {len(tool_modules)} tool modules — path bug?"

    transmitting = _transmitting_functions()
    assert "iaiops.connectors.sparkplug.ops.mqtt_publish" in transmitting
    assert "iaiops.core.llm.ollama.complete" in transmitting
    assert "iaiops.core.sink.influxdb.write" in transmitting


def test_known_egress_tools_are_flagged_by_the_scan() -> None:
    """The scan finds the audited surface — proving it is not matching nothing.

    Complements ``tests/test_no_egress_gate.py``, which checks the same set at
    runtime via the registry: this one proves the STATIC path also sees them.
    """
    transmitting = _transmitting_functions()
    flagged: set[str] = set()
    for path in sorted((REPO_ROOT / TOOLS_DIR).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        imports = _import_sources(tree)
        flagged |= {
            fn.name
            for fn in _functions(tree)
            if _is_mcp_tool(fn) and _reaches_transport(fn, imports, transmitting)
        }
    assert flagged == {
        "historian_push",
        "mqtt_publish",
        "rca_narrate",
        "stream_publish",
        "stream_publish_event",
    }


def test_local_file_writers_are_not_flagged() -> None:
    """``export_data`` writes a local file — the scan must leave it alone.

    Pinned so a future widening of ``SEND_PRIMITIVES`` (e.g. adding ``write``)
    fails here instead of quietly withholding an offline workflow.
    """
    path = REPO_ROOT / TOOLS_DIR / "export_tools.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    imports = _import_sources(tree)
    transmitting = _transmitting_functions()
    for fn in _functions(tree):
        if fn.name == "export_data":
            assert _reaches_transport(fn, imports, transmitting) is False
            return
    pytest.fail("export_data not found in mcp_server/tools/export_tools.py")
