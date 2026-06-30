"""Live MQTT / Sparkplug B → UNS governance bridge (consume-first, BOUNDED).

UNS governance (``uns_topic_audit`` / ``uns_schema_drift``) analyzes data the
caller *provides* — a topic list, two NBIRTH snapshots. This module closes the
loop: it captures those inputs from a LIVE broker over a bounded window (the same
``ops._collect`` collector used everywhere — up to N messages OR a timeout,
whichever first — never an open-ended loop), then feeds them straight into the
existing analyzers.

  * ``uns_live_audit``      — capture the live topic tree, then ``uns_topic_audit``.
  * ``sparkplug_live_schema`` — capture NBIRTH/DBIRTH, build the drift-ready
    ``{node: {metric: datatype}}`` dict ``uns_schema_drift`` expects.
  * ``uns_live_drift``      — capture the live schema, compare it to a provided
    baseline via ``uns_schema_drift``.

All read-only. The capture is bounded by ``max_msgs`` and ``duration_s`` (both
clamped inside ``ops._collect``), so it always terminates.
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.sparkplug import ops
from iaiops.core.brain import uns_governance as uns
from iaiops.core.brain._shared import s

# Discovery-style defaults: a wider message budget than a single sample, since an
# audit/schema capture wants to see the whole tree / every node's BIRTH.
DEFAULT_DURATION_S = ops.DEFAULT_TIMEOUT_S
DEFAULT_MAX_MSGS = ops.MAX_MESSAGES
_BIRTH_TYPES = ("NBIRTH", "DBIRTH")


def _node_id(parsed: dict) -> str:
    """Stable node identity for schema drift: group/edge[/device]."""
    base = f"{parsed['group_id']}/{parsed['edge_node_id']}"
    return f"{base}/{parsed['device_id']}" if parsed["device_id"] else base


def _capture_topics(target: Any, topic: str, max_msgs: int, duration_s: int) -> dict:
    """Bounded live capture → the unique topic set (the ``uns_topic_audit`` input)."""
    msgs = ops._collect(target, topic, max_msgs, duration_s)
    topics = sorted({m["topic"] for m in msgs})
    return {
        "endpoint": s(target.name, 64),
        "topic": s(topic, 128),
        "observed_messages": len(msgs),
        "unique_topics": len(topics),
        "topics": [s(t, 128) for t in topics][: ops.MAX_MESSAGES],
    }


def uns_live_audit(
    target: Any,
    topic: str = "#",
    duration_s: int = DEFAULT_DURATION_S,
    max_msgs: int = DEFAULT_MAX_MSGS,
    allowed_roots: list[str] | None = None,
    min_segments: int = 0,
    max_leaf_parents: int = 5,
) -> dict:
    """[READ] Capture the live UNS topic tree (bounded) then audit naming + sprawl.

    Subscribes to ``topic`` (default ``#``), collects up to ``max_msgs`` messages
    or until ``duration_s`` elapses (whichever first), then runs ``uns_topic_audit``
    over the observed topics. Returns the full audit plus a ``capture`` block
    recording what the live window actually saw.
    """
    capture = _capture_topics(target, topic or "#", max_msgs, duration_s)
    audit = uns.uns_topic_audit(
        capture["topics"], allowed_roots, min_segments, max_leaf_parents
    )
    return {**audit, "capture": capture}


def sparkplug_live_schema(
    target: Any,
    topic: str = "spBv1.0/#",
    duration_s: int = DEFAULT_DURATION_S,
    max_msgs: int = DEFAULT_MAX_MSGS,
) -> dict:
    """[READ] Capture live NBIRTH/DBIRTH (bounded) → drift-ready node/metric schema.

    Returns ``schema`` as ``{node: {metric: datatype}}`` (node = group/edge[/device]),
    built from the decoded BIRTH metrics observed in the window. That dict is exactly
    the shape ``uns_schema_drift`` accepts — use it as a baseline or a current snapshot.

    A Sparkplug BIRTH carries the node's FULL metric state, so when a node re-BIRTHs
    within the window the LAST BIRTH wins (replaces, not unions) — otherwise a metric
    REMOVED in a later BIRTH would linger and mask a real schema drift.
    """
    topic = topic or "spBv1.0/#"
    msgs = ops._collect(target, topic, max_msgs, duration_s)
    schema: dict[str, dict[str, str]] = {}
    birth_count = 0
    for m in msgs:
        parsed = ops._parse_sparkplug_topic(m["topic"])
        if not parsed or parsed["message_type"].upper() not in _BIRTH_TYPES:
            continue
        decoded = ops.decode_sparkplug_payload(m["payload"])
        if decoded.get("encoding") != "sparkplug_b":
            continue
        # Last BIRTH in the window wins — rebuild the node's metric set from scratch.
        schema[_node_id(parsed)] = {
            s(metric["name"], 96): s(str(metric.get("datatype", "")), 32)
            for metric in decoded["metrics"]
            if metric.get("name")
        }
        birth_count += 1
    return {
        "endpoint": s(target.name, 64),
        "topic": s(topic, 128),
        "message_count": len(msgs),
        "birth_count": birth_count,
        "node_count": len(schema),
        "schema": schema,
        "note": "Drift-ready {node:{metric:datatype}} captured live from NBIRTH/DBIRTH "
        "(bounded window). Feed it to uns_schema_drift as a baseline or current snapshot. "
        "Re-run with a longer duration_s if some nodes had not re-published BIRTH.",
    }


def uns_live_drift(
    target: Any,
    baseline: Any,
    topic: str = "spBv1.0/#",
    duration_s: int = DEFAULT_DURATION_S,
    max_msgs: int = DEFAULT_MAX_MSGS,
) -> dict:
    """[READ] Capture the live Sparkplug schema (bounded) and diff it vs a baseline.

    Captures the current node/metric definitions from live BIRTHs, then runs
    ``uns_schema_drift(baseline, current)`` — added / removed / type-changed metrics
    per node with a none/additive/breaking verdict. The ``capture`` block records
    how many BIRTHs/nodes the live window observed.
    """
    current = sparkplug_live_schema(target, topic, duration_s, max_msgs)
    drift = uns.uns_schema_drift(baseline, current["schema"])
    return {
        **drift,
        "capture": {
            "endpoint": current["endpoint"],
            "topic": current["topic"],
            "message_count": current["message_count"],
            "birth_count": current["birth_count"],
            "node_count": current["node_count"],
        },
    }


__all__ = ["uns_live_audit", "sparkplug_live_schema", "uns_live_drift"]
