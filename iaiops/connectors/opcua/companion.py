"""Find nodes a device declares through OPC UA companion specs (read-only walk).

The catalogue — which types, which values, which spec sections — is pure and
lives in :mod:`iaiops.core.brain.companion_specs`. This module only walks the
address space, resolves each Object's TypeDefinition (and its supertypes, so a
vendor subtype still matches), and reads the declared ``CurrentState/Number``.

Nothing is written, and nothing here sets a role: the output is SUGGESTIONS with
their evidence, which a person confirms in ``iaiops tags apply`` (D16).

**Bounded by what it costs the server, not by what it finds.** Each browse
returns its children's NodeClass, BrowseName and TypeDefinition in one service
call (no per-child reads), and every child seen counts against
:data:`MAX_NODES`. A walk that hits the budget, or that could not read part of
the tree, says so: absence of a declaration is not evidence there is none.
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.opcua.ops import _coerce_value, opcua_session
from iaiops.core.brain import companion_specs as cs
from iaiops.core.brain._shared import s
from iaiops.core.runtime.envelope import envelope_fields

#: Children examined (every node class), across the whole walk.
MAX_NODES = 20_000
MAX_DEPTH = 10
#: Supertype hops followed from an instance's type. A vendor rarely nests more
#: than two levels; the cap keeps a malformed type graph from looping.
MAX_SUPERTYPE_HOPS = 6
OBJECTS_NODE = "i=85"
_HAS_SUBTYPE = 45  # ua.ObjectIds.HasSubtype
_INCOMPLETE = "Walk incomplete — absence of a declaration is not evidence there is none."


def _name(text: Any, limit: int) -> str:
    """A device string for display: sanitised AND folded to one line."""
    return s(cs.one_line(text), limit)


def _inverse() -> Any:
    from asyncua import ua

    return ua.BrowseDirection.Inverse


class _TypeResolver:
    """``type node id → [(namespace_uri, type_name), …]`` up the supertype chain, cached."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._namespaces = [str(n) for n in client.get_namespace_array()]
        self._cache: dict[str, list[tuple[str, str]]] = {}

    def _uri(self, index: int) -> str:
        return self._namespaces[index] if 0 <= index < len(self._namespaces) else ""

    def chain(self, type_id: Any) -> list[tuple[str, str]]:
        key = type_id.to_string()
        if key in self._cache:
            return self._cache[key]
        chain: list[tuple[str, str]] = []
        node = self._client.get_node(type_id)
        for _ in range(MAX_SUPERTYPE_HOPS):
            try:
                name = node.read_browse_name()
                # BrowseName namespace AND NodeId namespace must agree: a type whose
                # name merely claims the spec's namespace is still only a name.
                if int(name.NamespaceIndex) != int(node.nodeid.NamespaceIndex):
                    break
                chain.append((self._uri(int(name.NamespaceIndex)), str(name.Name)))
                parents = node.get_references(refs=_HAS_SUBTYPE, direction=_inverse())
            except Exception:  # noqa: BLE001 — an unreadable type ends the chain
                break
            if not parents:
                break
            node = self._client.get_node(parents[0].NodeId)
        self._cache[key] = chain
        return chain


class _Walk:
    """One bounded walk: the budget, the findings, and what could not be read."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.types = _TypeResolver(client)
        self.seen = 0
        self.unreadable = 0
        self.exhausted = False
        self.out: dict[str, list] = {"suggestions": [], "recognised_without_role": []}

    def children(self, node: Any) -> list[Any]:
        """One browse; every description returned spends budget."""
        if self.exhausted:
            return []
        try:
            refs = list(node.get_children_descriptions())
        except Exception:  # noqa: BLE001 — counted, never silent
            self.unreadable += 1
            return []
        room = MAX_NODES - self.seen
        if len(refs) > room:
            refs, self.exhausted = refs[:room], True
        self.seen += len(refs)
        return refs

    def child(self, node: Any, name: str) -> Any | None:
        """A direct child by browse NAME, inside a type already matched (not classification)."""
        for ref in self.children(node):
            if str(ref.BrowseName.Name) == name:
                return self.client.get_node(ref.NodeId)
        return None

    def recognised(self, node_id: str, path: str, spec_id: str, type_name: str, why: str) -> None:
        self.out["recognised_without_role"].append(
            {
                "node_id": s(node_id, 128),
                "browse_path": _name(path, 256),
                "spec_id": spec_id,
                "type": type_name,
                "why_no_role": why,
            }
        )


def _match(walk: _Walk, ref: Any, path: str, chain: list[tuple[str, str]]) -> None:
    """Record what this one object's type chain declares."""
    instance_type = chain[0][1] if chain else ""
    node_id = ref.NodeId.to_string()
    for uri, type_name in chain:
        rule = cs.state_rule(uri, type_name)
        if rule is not None:
            _match_state(walk, ref, path, rule, instance_type)
            return
        reason = cs.MODE_TYPES.get((uri, type_name)) or cs.SUBSTATE_TYPES.get((uri, type_name))
        if reason is not None:
            spec_id = "packml" if uri == cs.PACKML_NS else "machinery"
            walk.recognised(node_id, path, spec_id, type_name, reason)
            return
        children = cs.recognised_children(uri, type_name)
        if children:
            obj = walk.client.get_node(ref.NodeId)
            names = {str(r.BrowseName.Name): r for r in walk.children(obj)}
            for spec_child in children:
                if spec_child.child in names:
                    walk.recognised(
                        names[spec_child.child].NodeId.to_string(),
                        f"{path}/{spec_child.child}",
                        spec_child.spec_id,
                        type_name,
                        spec_child.why_no_role,
                    )
            return


def _match_state(walk: _Walk, ref: Any, path: str, rule: cs.StateRule, instance_type: str) -> None:
    obj = walk.client.get_node(ref.NodeId)
    current = walk.child(obj, cs.STATE_NUMBER_PATH[0])
    number = walk.child(current, cs.STATE_NUMBER_PATH[1]) if current is not None else None
    if number is None:
        walk.recognised(
            ref.NodeId.to_string(),
            path,
            rule.spec_id,
            rule.type_name,
            "The device instantiates this state machine but exposes no "
            "CurrentState/Number (optional in OPC 10000-16 §4.4.3). CurrentState "
            "itself is localised text, so no language-independent running value "
            "can be suggested. Declare it by hand after watching the value.",
        )
        return
    try:
        value = _coerce_value(number.read_value())
    except Exception:  # noqa: BLE001 — the declaration stands even if the read fails
        value = None
    walk.out["suggestions"].append(
        cs.suggestion(
            rule,
            node_id=s(number.nodeid.to_string(), 128),
            browse_path=_name(f"{path}/{'/'.join(cs.STATE_NUMBER_PATH)}", 256),
            instance_type=_name(instance_type, 128),
            current_value=value,
        )
    )


def _summary(walk: _Walk, objects: int, depth_cap: int, pending: bool) -> dict[str, Any]:
    incomplete = []
    if walk.exhausted:
        incomplete.append(f"stopped at the {MAX_NODES}-node budget")
    if walk.unreadable:
        incomplete.append(f"{walk.unreadable} node(s) could not be browsed")
    return {
        **walk.out,
        "objects_examined": objects,
        "nodes_examined": walk.seen,
        "unreadable": walk.unreadable,
        "max_depth": depth_cap,
        "note": (
            "Suggestions come from TYPE DEFINITIONS the device instantiates (OPC UA "
            "companion specs), never from names. They pre-fill read-only columns in "
            "`iaiops tags export --suggest`; a person confirms each one by setting "
            "`role`. Nothing here declares a role."
            + (f" INCOMPLETE: {'; '.join(incomplete)}." if incomplete else "")
        ),
        # Counts NODES examined — what the budget bounds.
        **envelope_fields(
            returned=walk.seen,
            more_available=walk.exhausted or pending or bool(walk.unreadable),
            note=_INCOMPLETE,
        ),
    }


def walk_companion(
    client: Any, root: str = OBJECTS_NODE, max_depth: int = MAX_DEPTH
) -> dict[str, Any]:
    """Walk Objects under ``root`` on an open client and match companion types."""
    walk = _Walk(client)
    depth_cap = max(1, min(int(max_depth), MAX_DEPTH))
    visited: set[str] = set()
    objects = 0
    # Breadth-first: an Object reachable by a short path is reached by it first,
    # so the depth cap cannot hide it behind a longer path that got there earlier.
    queue: list[tuple[Any, tuple[str, ...], int]] = [(client.get_node(root), (), 0)]
    while queue and not walk.exhausted:
        node, path, depth = queue.pop(0)
        for ref in walk.children(node):
            nid = ref.NodeId.to_string()
            if nid in visited or int(ref.NodeId.NamespaceIndex) == 0:
                continue
            visited.add(nid)
            if getattr(ref.NodeClass, "name", str(ref.NodeClass)) != "Object":
                continue
            objects += 1
            child_path = (*path, cs.one_line(ref.BrowseName.Name))
            try:
                chain = walk.types.chain(ref.TypeDefinition)
            except Exception:  # noqa: BLE001
                walk.unreadable += 1
                chain = []
            _match(walk, ref, "/".join(child_path), chain)
            if depth + 1 < depth_cap:
                queue.append((client.get_node(ref.NodeId), child_path, depth + 1))
    walk.out["suggestions"].sort(key=lambda h: h["browse_path"])
    walk.out["recognised_without_role"].sort(key=lambda h: h["browse_path"])
    return _summary(walk, objects, depth_cap, bool(queue) and walk.exhausted)


def unexamined(reason: str) -> dict[str, Any]:
    """The result when no walk happened — explicitly incomplete, never 'nothing declared'."""
    return {
        "suggestions": [],
        "recognised_without_role": [],
        "error": s(reason, 200),
        "note": "Not examined — absence of a declaration is not evidence there is none.",
        **envelope_fields(returned=0, more_available=True, note=_INCOMPLETE),
    }


def companion_hints(
    target: Any, root: str = OBJECTS_NODE, max_depth: int = MAX_DEPTH
) -> dict[str, Any]:
    """[READ] Open a session and return companion-spec role suggestions."""
    with opcua_session(target) as client:
        result = walk_companion(client, root=root, max_depth=max_depth)
    return {"endpoint": s(getattr(target, "name", ""), 64), **result}


__all__ = ["MAX_NODES", "companion_hints", "unexamined", "walk_companion"]
