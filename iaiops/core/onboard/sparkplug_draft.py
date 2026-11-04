"""Turn observed BIRTH metrics into an unconfirmed point-list proposal.

No role, meaning, or completeness is inferred. A bounded capture can miss an
entire node; this output is only a review queue for an engineer.
"""

from __future__ import annotations

from typing import Any

MAX_DRAFT_POINTS = 5000


def _require_collectable_target(target: Any) -> None:
    if str(getattr(target, "protocol", "")).lower() != "mqtt":
        raise ValueError("A point draft requires a configured MQTT endpoint")
    if float(getattr(target, "stale_after_s", 0) or 0) <= 0:
        raise ValueError("Set endpoint stale_after_s before drafting collectable points")


def capture_point_draft(
    target: Any, topic: str = "spBv1.0/#", duration_s: int = 30, max_msgs: int = 500
) -> dict[str, Any]:
    """Check collection prerequisites before any broker subscription."""
    _require_collectable_target(target)
    from iaiops.connectors.sparkplug import live

    result = point_draft(live.sparkplug_live_schema(target, topic, duration_s, max_msgs), target)
    result["capture"]["requested_duration_s"] = duration_s
    result["capture"]["requested_max_msgs"] = max_msgs
    return result


def point_draft(capture: dict[str, Any], target: Any) -> dict[str, Any]:
    """Propose collectable refs from one Sparkplug live-schema capture."""
    _require_collectable_target(target)
    schema = capture.get("schema") or {}
    if not isinstance(schema, dict) or not schema:
        raise ValueError("No BIRTH schema observed; no point list can be proposed")
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for node, metrics in sorted(schema.items()):
        if not isinstance(node, str) or not isinstance(metrics, dict):
            raise ValueError("Malformed BIRTH schema")
        for metric, datatype in sorted(metrics.items()):
            if not isinstance(metric, str) or not metric or ":" in node or ":" in metric:
                skipped.append({"node": str(node), "metric": str(metric), "reason": "unusable ref"})
                continue
            if len(rows) >= MAX_DRAFT_POINTS:
                skipped.append({"node": node, "metric": metric, "reason": "draft row cap"})
                continue
            rows.append(
                {
                    "ref": f"{node}:{metric}",
                    "label": "",
                    "role": "",
                    "datatype_observed": str(datatype),
                }
            )
    if not rows:
        raise ValueError("No collectable point ref was found in the observed BIRTH schema")
    return {
        "endpoint": str(getattr(target, "name", "")),
        "capture": {
            k: capture.get(k) for k in ("topic", "message_count", "birth_count", "node_count")
        },
        "candidate_tags": rows,
        "skipped": skipped,
        "complete": False,
        "note": (
            "A bounded BIRTH capture can miss nodes. Review refs and add chosen tags "
            "to config.yaml; role and label remain blank. Run tags export/apply "
            "for human semantic confirmation."
        ),
    }


__all__ = ["capture_point_draft", "point_draft"]
