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

RISK_TAG_RE = re.compile(
    r"^(\[DEPRECATED → [\w.]+\])?\[(READ|WRITE)\]\[risk=(low|medium|HIGH)\]"
)
# A bare (unparameterized) list/dict token — `list[` / `dict[` do not match.
BARE_GENERIC_RE = re.compile(r"(?<![\w.\[])(list|dict)(?!\[)")


def _registered_tools() -> dict:
    from mcp_server import _shared
    from mcp_server.server import register_profile

    register_profile("all")  # order-independent: register the full surface
    return dict(_shared.mcp._tool_manager._tools)


def _annotation_text(annotation: object) -> str:
    if isinstance(annotation, str):
        return annotation
    if annotation in (list, dict):
        return getattr(annotation, "__name__", str(annotation))
    return str(annotation)


@pytest.mark.unit
def test_no_bare_list_or_dict_parameter_annotations():
    offenders: list[str] = []
    for name, tool in sorted(_registered_tools().items()):
        sig = inspect.signature(tool.fn)
        for pname, param in sig.parameters.items():
            if param.annotation is inspect.Parameter.empty:
                continue
            text = _annotation_text(param.annotation)
            if BARE_GENERIC_RE.search(text):
                offenders.append(f"{name}({pname}: {text})")
    assert not offenders, f"bare list/dict parameter annotations: {offenders}"


@pytest.mark.unit
def test_docstring_first_line_carries_risk_tag():
    offenders: list[str] = []
    for name, tool in sorted(_registered_tools().items()):
        doc = inspect.getdoc(tool.fn) or ""
        first_line = doc.splitlines()[0] if doc else ""
        if not RISK_TAG_RE.match(first_line):
            offenders.append(f"{name}: {first_line[:80]!r}")
    assert not offenders, f"docstring first line missing risk tag: {offenders}"
