"""Stream-egress MCP tools — publish iaiops' OWN reads/findings to a bus (adapter belt).

Read-first safe: these publish data the agent already READ (normalized points) or the brain already
COMPUTED (an RCA verdict / alarm event) onto an EXTERNAL message bus — never a control write. Two
buses are supported and each has its own tool, because their connection arguments have nothing in
common: ``stream_publish`` speaks NATS, ``uns_publish`` speaks MQTT (the Unified Namespace a plant
usually already runs). Both clients are optional extras imported lazily.
"""

from typing import Any

from iaiops.core.egress import get_publisher
from iaiops.core.egress.base import MAX_MESSAGES, SUPPORTED_PUBLISHERS
from iaiops.core.governance import governed_tool
from iaiops.core.sink.base import normalize_points
from mcp_server._shared import mcp, tool_errors


# egress=True: the whole point of these two is to put plant data on a broker the
# caller names. Low risk (they change no plant state) but they are exactly what
# IAIOPS_NO_EGRESS exists to withhold.
@mcp.tool()
@governed_tool(risk_level="low", egress=True, sensitive_params=["token"])
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
    # Deliberately narrower than SUPPORTED_PUBLISHERS: every argument this tool
    # takes (servers / token / tls) is NATS-shaped, so accepting another bus here
    # would pass validation and then fail on the constructor. Each bus gets its
    # own tool rather than a union of mutually exclusive arguments.
    if kind != "nats":
        raise ValueError(
            f"stream_publish speaks NATS; got publisher '{publisher}'. "
            f"For MQTT / a Unified Namespace use uns_publish instead."
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


# Same gate, same risk class as stream_publish — and the reasoning matters, because
# the connector already has an MQTT write tool at risk_level="high". The difference
# is what a caller controls: mqtt_publish takes an arbitrary topic AND an arbitrary
# payload, which is indistinguishable from a Sparkplug NCMD/DCMD to a live
# controller. Here the topic is always <prefix>/<metric> and the payload is always a
# telemetry record, so no combination of arguments reaches a command channel.
@mcp.tool()
@governed_tool(risk_level="low", egress=True, sensitive_params=["password"])
@tool_errors("dict")
def uns_publish(
    points: list[dict[str, Any]],
    topic_prefix: str = "iaiops",
    host: str = "localhost",
    port: int = 0,
    username: str = "",
    password: str = "",
    use_tls: bool = False,
    qos: int = 0,
    retain: bool = False,
) -> dict:
    """[READ][risk=low] Publish already-read normalized points to an MQTT broker / UNS.

    Egress of data the agent already READ — NOT a control write. Each numeric point becomes a JSON
    message on ``<topic_prefix>/<metric>``, with a dotted metric nested into topic levels
    (``line1.temp`` -> ``plant/line1/temp``) so a Unified Namespace stays browsable. Non-numeric
    points are skipped (use a historian sink for text/state). The topic is always derived from
    ``topic_prefix`` — it is never taken verbatim, so this cannot address a command topic. Needs the
    extra: pip install iaiops[mqtt].

    Args:
        points: Collected point dicts (e.g. from *_read_many): {ref/metric, value, timestamp, ...}.
        topic_prefix: Root of the topic tree (default 'iaiops'); wildcards are stripped.
        host: Broker hostname or IP (default localhost).
        port: Broker port; 0 picks 8883 with TLS else 1883.
        username: Optional broker username.
        password: Optional broker password.
        use_tls: Use TLS to the broker.
        qos: MQTT QoS 0/1/2 (default 0, fire-and-forget); values outside 0-2 are clamped.
        retain: Ask the broker to retain the last value per topic (useful for a UNS).

    Returns dict: {publisher, topic_prefix, broker, received, published, skipped_non_numeric}.

    Example: uns_publish(points=[{"ref": "line1.temp", "value": 21.5}], topic_prefix="plant",
        host="10.0.0.5").
    """
    pts = normalize_points(list(points or [])[:MAX_MESSAGES])
    numeric = [p for p in pts if p.get("numeric")]
    pub = get_publisher(
        "mqtt",
        host=host,
        port=port,
        topic_prefix=topic_prefix,
        username=username,
        password=password,
        use_tls=use_tls,
        qos=qos,
        retain=retain,
    )
    try:
        published = pub.publish_points(numeric)
    finally:
        pub.close()
    return {
        "publisher": "mqtt",
        "topic_prefix": topic_prefix,
        "broker": f"{host}:{port or (8883 if use_tls else 1883)}",
        "received": len(pts),
        "published": published,
        "skipped_non_numeric": len(pts) - len(numeric),
    }


@mcp.tool()
@governed_tool(risk_level="low", egress=True, sensitive_params=["token"])
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
