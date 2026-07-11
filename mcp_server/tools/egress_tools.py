"""Stream-egress MCP tools — publish iaiops' OWN reads/findings to a bus (adapter belt).

Read-first safe: these publish data the agent already READ (normalized points) or the brain already
COMPUTED (an RCA verdict / alarm event) onto an EXTERNAL message bus (NATS) — never a control write.
The bus client is an optional extra (``pip install iaiops[nats]``), imported lazily.
"""

from typing import Any

from iaiops.core.egress import get_publisher
from iaiops.core.egress.base import MAX_MESSAGES, SUPPORTED_PUBLISHERS
from iaiops.core.governance import governed_tool
from iaiops.core.sink.base import normalize_points
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def stream_publish(
    points: list[dict[str, Any]],
    subject_prefix: str = "iaiops",
    servers: str = "nats://localhost:4222",
    token: str = "",
    tls: bool = False,
    publisher: str = "nats",
) -> dict:
    """[READ][risk=low] Publish already-read normalized points to a message bus (NATS).

    Egress of data the agent already READ — NOT a control write. Each numeric point becomes a JSON
    message on ``<subject_prefix>.tag.<metric>``; non-numeric points are skipped (use a historian
    sink for text/state). Needs the extra: pip install iaiops[nats].

    Args:
        points: Collected point dicts (e.g. from *_read_many): {ref/metric, value, timestamp, ...}.
        subject_prefix: NATS subject root (default 'iaiops').
        servers: Comma-separated NATS server URLs (default nats://localhost:4222).
        token: Optional NATS auth token.
        tls: Use TLS to the broker.
        publisher: Bus kind (currently 'nats').

    Returns dict: {publisher, subject_prefix, received, published, skipped_non_numeric}.

    Example: stream_publish(points=[{"ref": "line1.temp", "value": 21.5}], subject_prefix="plant").
    """
    kind = (publisher or "").strip().lower()
    if kind not in SUPPORTED_PUBLISHERS:
        raise ValueError(
            f"Unknown publisher '{publisher}'. Supported: {', '.join(SUPPORTED_PUBLISHERS)}."
        )
    pts = normalize_points(list(points or [])[:MAX_MESSAGES])
    numeric = [p for p in pts if p.get("numeric")]
    pub = get_publisher(kind, servers=servers, subject_prefix=subject_prefix, token=token, tls=tls)
    try:
        published = pub.publish_points(numeric)
    finally:
        pub.close()
    return {
        "publisher": kind,
        "subject_prefix": subject_prefix,
        "received": len(pts),
        "published": published,
        "skipped_non_numeric": len(pts) - len(numeric),
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def stream_publish_event(
    subject: str,
    event: dict[str, Any],
    servers: str = "nats://localhost:4222",
    token: str = "",
    tls: bool = False,
    subject_prefix: str = "iaiops",
    publisher: str = "nats",
) -> dict:
    """[READ][risk=low] Publish one computed event (RCA verdict / alarm) to a message bus (NATS).

    Egress of a finding the brain already COMPUTED — e.g. an RCA verdict or an alarm episode — to
    ``<subject_prefix>.<subject>`` as JSON. NOT a control write. Needs: pip install iaiops[nats].

    Args:
        subject: Event subject suffix (e.g. 'rca.verdict', 'alarm.flood').
        event: The event payload dict (published as JSON).
        servers/token/tls/subject_prefix/publisher: bus connection (see stream_publish).

    Returns dict: {publisher, subject, published}.

    Example: stream_publish_event(subject="rca.verdict", event={"primary_cause": "seal"}).
    """
    subj = (subject or "").strip()
    if not subj:
        raise ValueError("subject is required (e.g. 'rca.verdict').")
    kind = (publisher or "").strip().lower()
    if kind not in SUPPORTED_PUBLISHERS:
        raise ValueError(
            f"Unknown publisher '{publisher}'. Supported: {', '.join(SUPPORTED_PUBLISHERS)}."
        )
    pub = get_publisher(kind, servers=servers, subject_prefix=subject_prefix, token=token, tls=tls)
    try:
        published = pub.publish_event(subj, dict(event or {}))
    finally:
        pub.close()
    full_subject = f"{subject_prefix}.{subj.strip('.')}"
    return {"publisher": kind, "subject": full_subject, "published": published}
