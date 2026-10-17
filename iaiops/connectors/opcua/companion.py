"""Find nodes a device declares through OPC UA companion specs (read-only walk).

The catalogue — which types, which values, which spec sections — is pure and
lives in :mod:`iaiops.core.brain.companion_specs`. This module only walks the
address space, resolves each Object's TypeDefinition (and its supertypes, so a
vendor subtype of ``PackMLExecuteStateMachineType`` still matches), and reads
the declared ``CurrentState/Number``.

Nothing is written, and nothing here sets a role: the output is SUGGESTIONS with
their evidence, which a person confirms in ``iaiops tags apply`` (D16).

Bounded like the rest of discovery: object count, depth and supertype hops are
capped, and a truncated walk says so.
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.opcua.ops import _coerce_value, opcua_session
from iaiops.core.brain import companion_specs as cs
from iaiops.core.brain._shared import s
from iaiops.core.runtime.envelope import envelope_fields

MAX_OBJECTS = 2000
MAX_DEPTH = 10
#: Supertype hops followed from an instance's type. A vendor rarely nests more
#: than two levels; the cap keeps a malformed type graph from looping.
MAX_SUPERTYPE_HOPS = 6
OBJECTS_NODE = "i=85"
_HAS_SUBTYPE = 45  # ua.ObjectIds.HasSubtype


class _TypeResolver:
    """``node id → [(namespace_uri, type_name), …]`` up the supertype chain, cached."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._namespaces = [str(n) for n in client.get_namespace_array()]
        self._cache: dict[str, list[tuple[str, str]]] = {}

    def _qualified(self, node: Any) -> tuple[str, str]:
        name = node.read_browse_name()
        idx = int(name.NamespaceIndex)
        uri = self._namespaces[idx] if 0 <= idx < len(self._namespaces) else ""
        return uri, str(name.Name)

    def chain(self, type_node: Any) -> list[tuple[str, str]]:
        key = type_node.nodeid.to_string()
        if key in self._cache:
            return self._cache[key]
        chain: list[tuple[str, str]] = []
        node = type_node
        for _ in range(MAX_SUPERTYPE_HOPS):
            try:
                chain.append(self._qualified(node))
                parents = node.get_references(refs=_HAS_SUBTYPE, direction=_inverse())
            except Exception:  # noqa: BLE001 — an unreadable type ends the chain
                break
            if not parents:
                break
            node = self._client.get_node(parents[0].NodeId)
        self._cache[key] = chain
        return chain


def _inverse() -> Any:
    from asyncua import ua

    return ua.BrowseDirection.Inverse


def _child(node: Any, name: str) -> Any | None:
    """A direct child (component or property) by browse NAME, any namespace.

    Inherited children (``CurrentState``, ``Number``) are namespace 0; some
    servers put them in their own namespace. The name is matched, not the index —
    this is resolving a path inside a type the device already declared, not
    classifying by name.
    """
    try:
        children = node.get_children()
    except Exception:  # noqa: BLE001
        return None
    for child in children:
        try:
            if child.read_browse_name().Name == name:
                return child
        except Exception:  # noqa: BLE001
            continue
    return None


def _match(obj: Any, path: str, chain: list[tuple[str, str]], out: dict[str, list]) -> None:
    """Record what this one object's type chain declares."""
    instance_type = chain[0][1] if chain else ""
    for uri, type_name in chain:
        rule = cs.state_rule(uri, type_name)
        if rule is not None:
            _match_state(obj, path, rule, instance_type, out)
            return
        mode = cs.MODE_TYPES.get((uri, type_name))
        if mode is not None:
            out["recognised_without_role"].append(
                {
                    "node_id": s(obj.nodeid.to_string(), 128),
                    "browse_path": s(path, 256),
                    "spec_id": "machinery",
                    "type": type_name,
                    "why_no_role": mode,
                }
            )
            return
        children = cs.recognised_children(uri, type_name)
        if children:
            for spec_child in children:
                node = _child(obj, spec_child.child)
                if node is None:
                    continue
                out["recognised_without_role"].append(
                    {
                        "node_id": s(node.nodeid.to_string(), 128),
                        "browse_path": s(f"{path}/{spec_child.child}", 256),
                        "spec_id": spec_child.spec_id,
                        "type": type_name,
                        "why_no_role": spec_child.why_no_role,
                    }
                )
            return


def _match_state(
    obj: Any, path: str, rule: cs.StateRule, instance_type: str, out: dict[str, list]
) -> None:
    current = _child(obj, cs.STATE_NUMBER_PATH[0])
    number = _child(current, cs.STATE_NUMBER_PATH[1]) if current is not None else None
    if number is None:
        out["recognised_without_role"].append(
            {
                "node_id": s(obj.nodeid.to_string(), 128),
                "browse_path": s(path, 256),
                "spec_id": rule.spec_id,
                "type": rule.type_name,
                "why_no_role": (
                    "The device instantiates this state machine but exposes no "
                    "CurrentState/Number (optional in OPC 10000-16 §4.4.3). CurrentState "
                    "itself is localised text, so no language-independent running value "
                    "can be suggested. Declare it by hand after watching the value."
                ),
            }
        )
        return
    try:
        value = _coerce_value(number.read_value())
    except Exception:  # noqa: BLE001 — the declaration stands even if the read fails
        value = None
    out["suggestions"].append(
        cs.suggestion(
            rule,
            node_id=s(number.nodeid.to_string(), 128),
            browse_path=s(f"{path}/{'/'.join(cs.STATE_NUMBER_PATH)}", 256),
            instance_type=s(instance_type, 128),
            current_value=value,
        )
    )


def walk_companion(
    client: Any, root: str = OBJECTS_NODE, max_depth: int = MAX_DEPTH
) -> dict[str, Any]:
    """Walk Objects under ``root`` on an open client and match companion types."""
    resolver = _TypeResolver(client)
    out: dict[str, list] = {"suggestions": [], "recognised_without_role": []}
    visited: set[str] = set()
    examined = 0
    truncated = False
    stack: list[tuple[Any, tuple[str, ...], int]] = [(client.get_node(root), (), 0)]
    while stack:
        node, path, depth = stack.pop()
        try:
            children = node.get_children()
        except Exception:  # noqa: BLE001 — a node may not be browsable
            continue
        for child in children:
            try:
                nid = child.nodeid.to_string()
                if nid in visited or int(child.nodeid.NamespaceIndex) == 0:
                    continue
                visited.add(nid)
                if child.read_node_class().name != "Object":
                    continue
                name = child.read_browse_name().Name
            except Exception:  # noqa: BLE001 — skip an unreadable child
                continue
            if examined >= MAX_OBJECTS:
                truncated = True
                stack.clear()
                break
            examined += 1
            child_path = (*path, str(name))
            try:
                chain = resolver.chain(client.get_node(child.read_type_definition()))
            except Exception:  # noqa: BLE001
                chain = []
            _match(child, "/".join(child_path), chain, out)
            if depth + 1 < max_depth:
                stack.append((child, child_path, depth + 1))
    out["suggestions"].sort(key=lambda h: h["browse_path"])
    out["recognised_without_role"].sort(key=lambda h: h["browse_path"])
    return {
        **out,
        "objects_examined": examined,
        "note": (
            "Suggestions come from TYPE DEFINITIONS the device instantiates (OPC UA "
            "companion specs), never from names. They pre-fill read-only columns in "
            "`iaiops tags export --suggest`; a person confirms each one by setting "
            "`role`. Nothing here declares a role."
        ),
        # The envelope counts OBJECTS examined: that is what the cap bounds, and
        # a truncated walk may have missed declarations — absence is not evidence.
        **envelope_fields(
            returned=examined,
            more_available=truncated,
            note=f"Walk stopped at {MAX_OBJECTS} objects — absence is not evidence.",
        ),
    }


def companion_hints(
    target: Any, root: str = OBJECTS_NODE, max_depth: int = MAX_DEPTH
) -> dict[str, Any]:
    """[READ] Open a session and return companion-spec role suggestions."""
    depth = max(1, min(int(max_depth), MAX_DEPTH))
    with opcua_session(target) as client:
        result = walk_companion(client, root=root, max_depth=depth)
    return {"endpoint": s(getattr(target, "name", ""), 64), **result}


__all__ = ["MAX_OBJECTS", "companion_hints", "walk_companion"]
