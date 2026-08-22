"""The brain computes without a model — asserted, not claimed.

Every number this product puts in front of an operator is produced by
deterministic Python: the noisy-OR confidences, the alarm cascade, OEE, the
conservative baselines, the Theil-Sen trends. An LLM is used in exactly two
places and neither is load-bearing — ``rca_narrate`` rephrases an
already-computed, already-cited verdict, and an agent front-end decides *which*
tool to call. Remove the model and the outputs are byte-identical.

That property is why the product runs on an edge box with no model and no
network, and it is why a CLI front-end loses nothing against an agent one. It is
also the kind of property that decays silently: one convenient
``from iaiops.core.llm import ...`` inside a brain module and "our analysis needs
no model" quietly becomes false while every test stays green.

So it is a guard, in the same spirit as the discovery package's no-write guard:
the analysis layer is scanned for any route to a model, and an empty result is
the guarantee.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: Import prefixes that would put a model in the analysis path.
FORBIDDEN_PREFIXES = (
    "iaiops.core.llm",
    "openai",
    "anthropic",
    "ollama",
    "transformers",
    "llama_cpp",
    "langchain",
)

#: Layers that must stay computable without a model. ``core/llm`` is the
#: provider itself and ``mcp_server/tools/llm_tools.py`` is the opt-in narration
#: tool — both are allowed to know about models; nothing below them is.
GUARDED_PACKAGES = (
    "iaiops/core/brain",
    "iaiops/core/discovery",
    "iaiops/core/runtime",
    "iaiops/core/readiness",
    "iaiops/core/collect",
    "iaiops/connectors",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
    return found


def _scan(package: str) -> list[str]:
    root = _repo_root() / package
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _imports(tree):
            if module.startswith(FORBIDDEN_PREFIXES):
                findings.append(f"{path.relative_to(_repo_root())}:{lineno} imports {module}")
    return findings


@pytest.mark.parametrize("package", GUARDED_PACKAGES)
def test_the_analysis_layers_cannot_reach_a_model(package: str) -> None:
    """An empty result is the guarantee.

    If this fails, the honest options are to move the code into an opt-in tool
    beside ``rca_narrate``, or to stop saying the analysis runs without a model.
    Do not add an exception here — the exception IS the regression.
    """
    findings = _scan(package)
    assert findings == [], (
        f"{package} can reach a language model:\n  " + "\n  ".join(findings) + "\n\n"
        "Every number shown to an operator must be reproducible without one. "
        "Move it into an opt-in tool (see mcp_server/tools/llm_tools.py) instead."
    )


def test_the_guard_would_actually_fire() -> None:
    """A guard that has never been seen to fail is not evidence."""
    source = "from iaiops.core.llm import get_provider\nx = 1\n"
    tree = ast.parse(source)
    assert any(module.startswith(FORBIDDEN_PREFIXES) for _, module in _imports(tree))


def test_the_narration_tool_is_where_the_model_lives() -> None:
    """The complement: the opt-in path must still exist and still be opt-in.

    A guard that passed because the feature was deleted would be worthless.
    """
    narrator = _repo_root() / "mcp_server/tools/llm_tools.py"
    assert narrator.exists(), "the opt-in narration tool is gone"
    text = narrator.read_text(encoding="utf-8")
    assert "rca_narrate" in text
    # It rephrases a verdict that was already computed and already cited.
    assert "verdict" in text
