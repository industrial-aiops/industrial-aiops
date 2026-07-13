"""B7 — MCP tool-signature polish contract.

Walks every registered MCP tool and asserts:

  (a) no bare ``list``/``dict`` parameter annotations — element types must be
      parameterized generics (``list[str]``, ``dict[str, float]``, …) so the
      LLM-facing JSON schema carries the real element types;
  (b) the first docstring line carries the unified risk tag
      ``[READ|WRITE][risk=low|medium|HIGH]`` (a ``[DEPRECATED → new_name]``
      prefix from the B4 rename grace period is allowed).
"""

import inspect
import re

import pytest

RISK_TAG_RE = re.compile(r"^(\[DEPRECATED → [\w.]+\])?\[(READ|WRITE)\]\[risk=(low|medium|HIGH)\]")
# A bare (unparameterized) list/dict token — `list[` / `dict[` do not match.
BARE_GENERIC_RE = re.compile(r"(?<![\w.\[])(list|dict)(?!\[)")


# Tool collection: the ``full_tool_registry`` fixture (tests/conftest.py)
# registers the FULL surface incl. EDITION_MODULES tools —
# ``register_profile("all")`` alone covers only the protocol groups + brain and
# would skip the ~25 edition tools (bas/ignition/clinical/...), including the
# write tool ``bas_command``.


def _annotation_text(annotation: object) -> str:
    if isinstance(annotation, str):
        return annotation
    if annotation in (list, dict):
        return getattr(annotation, "__name__", str(annotation))
    return str(annotation)


@pytest.mark.unit
def test_no_bare_list_or_dict_parameter_annotations(full_tool_registry):
    offenders: list[str] = []
    for name, tool in sorted(full_tool_registry.items()):
        sig = inspect.signature(tool.fn)
        for pname, param in sig.parameters.items():
            if param.annotation is inspect.Parameter.empty:
                continue
            text = _annotation_text(param.annotation)
            if BARE_GENERIC_RE.search(text):
                offenders.append(f"{name}({pname}: {text})")
    assert not offenders, f"bare list/dict parameter annotations: {offenders}"


@pytest.mark.unit
def test_docstring_first_line_carries_risk_tag(full_tool_registry):
    offenders: list[str] = []
    for name, tool in sorted(full_tool_registry.items()):
        doc = inspect.getdoc(tool.fn) or ""
        first_line = doc.splitlines()[0] if doc else ""
        if not RISK_TAG_RE.match(first_line):
            offenders.append(f"{name}: {first_line[:80]!r}")
    assert not offenders, f"docstring first line missing risk tag: {offenders}"
