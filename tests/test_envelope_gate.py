"""Repo-wide CI gate: a bounded return must carry the standard envelope.

The point of this file is that the NEXT list-returning tool is caught by the
suite, not by a reviewer noticing. It is a static (AST) scan of ``iaiops/`` and
``mcp_server/`` — it never imports or calls anything, so it needs no devices and
adds no runtime cost.

See :mod:`iaiops.core.runtime.envelope` for the contract and why it exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from iaiops.core.runtime.envelope import ENVELOPE_KEYS

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_PACKAGES = ("iaiops", "mcp_server")

#: The legacy key that means "this return is bounded".
LEGACY_TRUNCATION_KEY = "truncated"

#: Constructing the envelope through one of these is the only accepted proof.
#: Hand-spelled envelope keys are deliberately NOT accepted: the helper is what
#: keeps the five keys consistent and the boundary logic correct.
ENVELOPE_BUILDERS = frozenset({"envelope_fields", "bounded"})

#: Qualified ``module::function`` names exempted from the gate, each with a
#: written justification. Empty on purpose — an exemption is a decision that
#: should have to be argued for in review, not a quiet default.
ALLOWLIST: dict[str, str] = {}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for package in SCANNED_PACKAGES:
        files.extend(sorted((REPO_ROOT / package).rglob("*.py")))
    assert files, "found no source files to scan — the gate would pass vacuously"
    return files


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _emits_truncation_key(fn: ast.AST) -> bool:
    """True if the function writes a top-level ``"truncated"`` key.

    Covers both spellings used in this repo: a dict literal key
    (``{"truncated": ...}``) and a subscript assignment
    (``result["truncated"] = ...``).
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == LEGACY_TRUNCATION_KEY:
                    return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == LEGACY_TRUNCATION_KEY
        ):
            return True
    return False


def _returns_a_capped_list(fn: ast.AST) -> bool:
    """True if a ``return {...}`` literal caps one of its values with ``x[:n]``.

    ``[:cap]`` in a returned dict value is this repo's idiom for "this list was
    bounded", so the result is exactly as incomplete as a ``truncated`` flag
    would say — and must therefore declare it.
    """
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
            continue
        for value in node.value.values:
            for inner in ast.walk(value):
                if (
                    isinstance(inner, ast.Subscript)
                    and isinstance(inner.slice, ast.Slice)
                    and inner.slice.lower is None
                    and inner.slice.upper is not None
                ):
                    return True
    return False


def _builds_envelope(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in ENVELOPE_BUILDERS:
                return True
    return False


def _offenders(predicate, *, restrict_to: str | None = None) -> list[str]:
    found: list[str] = []
    for path in _python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if restrict_to and not rel.startswith(restrict_to):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for fn in _functions(tree):
            qualified = f"{rel}::{fn.name}"
            if qualified in ALLOWLIST:
                continue
            if predicate(fn) and not _builds_envelope(fn):
                found.append(qualified)
    return found


def test_truncation_flag_implies_envelope() -> None:
    """Every function emitting a ``truncated`` key must build the envelope.

    This is the primary gate. A function that already knows it truncated has no
    excuse for not saying so in the standard, machine-checkable way.
    """
    offenders = _offenders(_emits_truncation_key)
    assert not offenders, (
        "these functions emit a 'truncated' key without building the standard "
        f"envelope via {sorted(ENVELOPE_BUILDERS)} — see iaiops/core/runtime/"
        f"envelope.py: {offenders}"
    )


def test_capped_returns_carry_envelope() -> None:
    """MCP tools that return a ``x[:cap]``-sliced list must build the envelope.

    DOCUMENTED LIMITS — this is the strongest honest approximation available to
    a static scan, not a complete proof. It does NOT catch:

    * a tool that returns a list with no cap and no truncation notion at all —
      there is nothing in the source to distinguish it from a complete answer,
      and flagging every list-returning function would be a false-positive
      machine that reviewers would learn to ignore;
    * capping done outside the ``return`` statement (``rows = rows[:cap]`` on an
      earlier line, or inside a helper the tool calls) — the slice is then not a
      value of the returned dict literal;
    * caps expressed as ``itertools.islice``, ``heapq.nlargest``, a LIMIT in a
      SQL string, or a device-side row limit;
    * whether the numbers passed to the envelope are CORRECT. That is what the
      per-call-site tests in ``tests/test_return_envelope.py`` are for; this gate
      only proves the envelope is constructed by the shared helper.

    It is deliberately scoped to ``mcp_server/tools/`` — the model-facing
    surface, where a missing truncation flag becomes a misdiagnosis — because
    the ``[:n]`` idiom is also used internally for excerpts and previews that are
    not list returns, and scanning those would produce noise rather than signal.
    """
    offenders = _offenders(_returns_a_capped_list, restrict_to="mcp_server/tools/")
    assert not offenders, (
        "these MCP tools return a capped ('x[:n]') list without building the "
        f"standard envelope via {sorted(ENVELOPE_BUILDERS)}: {offenders}"
    )


def test_gate_actually_has_teeth() -> None:
    """Guard the guard: the predicates must fire on a known-bad snippet.

    Without this, a refactor that broke the AST matching would leave both gates
    above passing vacuously forever.
    """
    bad = ast.parse("def tool():\n    return {'rows': rows[:10], 'truncated': len(rows) > 10}\n")
    fn = next(_functions(bad))
    assert _emits_truncation_key(fn) is True
    assert _returns_a_capped_list(fn) is True
    assert _builds_envelope(fn) is False

    good = ast.parse(
        "def tool():\n"
        "    return {'rows': rows[:10], 'truncated': len(rows) > 10,\n"
        "            **envelope_fields(returned=len(rows[:10]), total=len(rows))}\n"
    )
    assert _builds_envelope(next(_functions(good))) is True


def test_gate_scans_a_real_and_non_trivial_surface() -> None:
    """The scan must actually cover the packages, and find the migrated sites.

    A silent path/rename bug would otherwise make the gates above pass by
    scanning nothing.
    """
    files = _python_files()
    assert len(files) > 100, f"only {len(files)} files scanned — path bug?"
    known = [
        fn
        for path in files
        for fn in _functions(ast.parse(path.read_text(encoding="utf-8"), str(path)))
        if _emits_truncation_key(fn)
    ]
    assert len(known) >= 8, f"expected the migrated truncating functions, found {len(known)}"


def test_envelope_keys_are_stable() -> None:
    """The five key names are a published contract — changing one breaks readers."""
    assert ENVELOPE_KEYS == (
        "items_returned",
        "items_total",
        "items_total_is_exact",
        "is_truncated",
        "truncation_note",
    )
