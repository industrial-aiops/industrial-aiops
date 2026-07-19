"""MQTT / Sparkplug B / UNS operations (consume-first), with full SpB decode.

The Unified Namespace (UNS) and Sparkplug B sit on top of MQTT (``paho-mqtt``,
pure Python). This module is **consume/read primary**: it subscribes to a broker,
collects a BOUNDED number of messages (never an open-ended loop), and returns
them — decoded as JSON/text or full **Sparkplug B protobuf** where applicable.

Sparkplug B decoding is complete (not a hex preview): the payload protobuf is
parsed with a *vendored, byte-for-byte* copy of the official Eclipse Tahu
``sparkplug_b.proto`` generated module (:mod:`iaiops.connectors.sparkplug.sparkplug_b_pb2`,
depends only on ``protobuf``). Per metric we surface name, **alias** (resolved to
its name via the NBIRTH/DBIRTH model), datatype (Int/Float/Bool/String/DateTime/
DataSet/Template…), value, timestamp, and the ``is_historical`` / ``is_null``
flags. Rich datatypes are expanded, not skipped: a **DataSet** metric decodes to
columnar ``{columns, types, rows}`` (each cell decoded through its declared column
type), and a **Template** decodes to ``{template_ref, is_definition, version,
members, parameters}`` with members decoded recursively (nested DataSet/Template
included, bounded against pathological nesting). A birth/death + seq model tracks
node/device online state, builds the
alias→name map from BIRTH, applies NDATA/DDATA by alias, marks DEATH offline, and
flags ``seq`` gaps / out-of-order. STATE topics surface primary-host status.

Topic convention: ``spBv1.0/{group}/{msg_type}/{edge_node}/[device]`` (msg_type ∈
NBIRTH, DBIRTH, NDATA, DDATA, NDEATH, DDEATH, STATE).

``mqtt_publish`` is an OT-DANGEROUS command path: governed (high risk_tier), off
by default (dry-run). A published command has no automatic inverse.
未经授权勿对生产控制系统下发指令.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, mqtt_session
from iaiops.core.runtime.envelope import envelope_fields

MAX_MESSAGES = 500
MAX_METRICS = 1000
# Rich-type (DataSet / Template) decode caps — bound the structured output so a
# large table or a deeply nested Template instance can never blow up a tool result.
MAX_DATASET_ROWS = 2000  # rows returned from a DataSet metric
MAX_DATASET_COLUMNS = 256  # columns / column-types returned from a DataSet metric
MAX_TEMPLATE_MEMBERS = 1000  # member metrics returned from a Template metric
MAX_TEMPLATE_PARAMS = 256  # parameters returned from a Template metric
MAX_TEMPLATE_DEPTH = 8  # ceiling on nested-Template recursion (pathological guard)
DEFAULT_MESSAGES = 25
DEFAULT_TIMEOUT_S = 10
MAX_TIMEOUT_S = 60
_POLL_S = 0.05
_SEQ_MOD = 256  # Sparkplug B seq is an unsigned 8-bit rolling counter

# Sparkplug B DataType enum value → name (Eclipse Tahu sparkplug_b.proto).
_DATATYPE_NAMES = {
    0: "Unknown",
    1: "Int8",
    2: "Int16",
    3: "Int32",
    4: "Int64",
    5: "UInt8",
    6: "UInt16",
    7: "UInt32",
    8: "UInt64",
    9: "Float",
    10: "Double",
    11: "Boolean",
    12: "String",
    13: "DateTime",
    14: "Text",
    15: "UUID",
    16: "DataSet",
    17: "Bytes",
    18: "File",
    19: "Template",
    20: "PropertySet",
    21: "PropertySetList",
}

# Signed DataType enum value → bit width. Per the Sparkplug B spec, signed
# integers travel two's-complement in the UNSIGNED protobuf fields (Int8/16/32
# in ``int_value`` which is uint32; Int64 in ``long_value`` which is uint64), so
# the raw field value must be sign-reinterpreted at the declared width.
_SIGNED_INT_BITS = {1: 8, 2: 16, 3: 32, 4: 64}  # Int8 / Int16 / Int32 / Int64


def _reinterpret_signed(raw: int, datatype: int) -> int:
    """Sign-reinterpret a raw unsigned wire integer per the metric's datatype.

    Encoders differ in how much they mask (Tahu Python masks negatives to the
    full 32-bit field; others mask to the type width), so mask down to the
    declared width first, then flip values at/above the sign bit. Unsigned and
    unknown datatypes pass through unchanged.
    """
    bits = _SIGNED_INT_BITS.get(int(datatype))
    if bits is None:
        return raw
    raw = int(raw) & ((1 << bits) - 1)
    if raw >= 1 << (bits - 1):
        raw -= 1 << bits
    return raw


def _clamp_count(count: int) -> int:
    return max(1, min(int(count), MAX_MESSAGES))


def _clamp_timeout(timeout_s: int) -> int:
    return max(1, min(int(timeout_s), MAX_TIMEOUT_S))


def _collect(target: Any, topic: str, count: int, timeout_s: int) -> list[dict]:
    """Subscribe to ``topic`` and collect up to ``count`` messages (bounded).

    Factored out (and monkeypatched in tests) so the parsing/decoding tools can
    be exercised with synthetic messages and no live broker. Messages are kept in
    arrival order so the birth/death + seq model can be applied downstream.
    """
    topic = topic or getattr(target, "topic", "") or "#"
    count = _clamp_count(count)
    timeout_s = _clamp_timeout(timeout_s)
    buffer: list[dict] = []

    def _on_message(_client: Any, _userdata: Any, msg: Any) -> None:
        if len(buffer) < count:
            buffer.append({"topic": msg.topic, "payload": bytes(msg.payload)})

    with mqtt_session(target) as client:
        client.on_message = _on_message
        client.subscribe(topic)
        deadline = time.monotonic() + timeout_s
        while len(buffer) < count and time.monotonic() < deadline:
            time.sleep(_POLL_S)
    return buffer


# ─── Sparkplug B protobuf decode ─────────────────────────────────────────────


def _sparkplug_pb():
    """Return the vendored Sparkplug B protobuf module, or None if unavailable."""
    try:
        from iaiops.connectors.sparkplug import sparkplug_b_pb2

        return sparkplug_b_pb2
    except Exception:  # noqa: BLE001 — missing protobuf must not crash the tool
        return None


def _scalar_from_oneof(holder: Any, declared_type: int, str_cap: int = 512) -> Any:
    """Decode a scalar from a Sparkplug ``value`` oneof (DataSetValue / Parameter).

    These cells carry no datatype of their own — the governing DataType comes from
    the DataSet column (or the Template parameter's ``type``), so the signed integer
    fields must sign-reinterpret at that declared width, exactly as a top-level
    metric does. Returns None when the oneof is unset; an extension value is
    surfaced as a short structural preview (rare in practice).
    """
    which = holder.WhichOneof("value")
    if which is None:
        return None
    raw = getattr(holder, which)
    if which in ("int_value", "long_value"):
        return _reinterpret_signed(raw, declared_type)
    if which in ("float_value", "double_value", "boolean_value"):
        return raw
    if which == "string_value":
        return s(raw, str_cap)
    return s(str(raw), 128)  # extension_value — structural preview only


def _decode_dataset(dataset: Any) -> dict:
    """Decode a Sparkplug B DataSet metric to a columnar ``{columns, types, rows}``.

    Column ``types`` map the DataType enum to names, and every row cell is decoded
    through its governing column type (so signed integers in the table sign-
    reinterpret correctly). Rows/columns are bounded; ``row_count`` / ``truncated``
    report the true size versus what was returned.
    """
    type_ints = [int(t) for t in list(dataset.types)[:MAX_DATASET_COLUMNS]]
    columns = [s(c, 48) for c in list(dataset.columns)[:MAX_DATASET_COLUMNS]]
    types = [_DATATYPE_NAMES.get(t, str(t)) for t in type_ints]
    rows: list[list[Any]] = []
    for row in list(dataset.rows)[:MAX_DATASET_ROWS]:
        elements = list(row.elements)
        rows.append(
            [
                _scalar_from_oneof(elements[i], type_ints[i] if i < len(type_ints) else 0)
                for i in range(len(elements))
            ]
        )
    return {
        "dataset": True,
        "num_columns": int(getattr(dataset, "num_of_columns", 0)),
        "columns": columns,
        "types": types,
        "rows": rows,
        "row_count": len(dataset.rows),  # legacy key: the TRUE total, not len(rows)
        "truncated": len(dataset.rows) > MAX_DATASET_ROWS,  # legacy bool — see `is_truncated`
        **envelope_fields(returned=len(rows), total=len(dataset.rows)),
    }


def _decode_parameter(param: Any) -> dict:
    """Decode a Template Parameter to ``{name, type, value}`` (type-aware scalar)."""
    ptype = int(param.type)
    return {
        "name": s(param.name, 64),
        "type": _DATATYPE_NAMES.get(ptype, str(ptype)),
        "value": _scalar_from_oneof(param, ptype, 256),
    }


def _decode_template_member(metric: Any, depth: int) -> dict:
    """Decode one Template member metric to ``{name, type, value}``.

    The value is decoded recursively, so a member that is itself a DataSet or a
    nested Template expands fully (bounded by :data:`MAX_TEMPLATE_DEPTH`).
    """
    return {
        "name": s(metric.name, 96),
        "type": _DATATYPE_NAMES.get(int(metric.datatype), str(int(metric.datatype))),
        "value": None if metric.is_null else _metric_value(metric, depth),
    }


def _decode_template(template: Any, depth: int = 0) -> dict:
    """Decode a Sparkplug B Template metric to a structured instance/definition.

    Surfaces ``template_ref``, ``is_definition``, ``version``, the recursively
    decoded ``members`` (each a metric, which may itself be a nested DataSet or
    Template), and typed ``parameters``. ``depth`` bounds pathological nesting: at
    the ceiling members are omitted (``members_truncated``) rather than recursing
    without limit.
    """
    if depth >= MAX_TEMPLATE_DEPTH:
        members: list[dict] = []
        members_truncated = bool(len(template.metrics))
    else:
        members = [
            _decode_template_member(m, depth + 1)
            for m in list(template.metrics)[:MAX_TEMPLATE_MEMBERS]
        ]
        members_truncated = len(template.metrics) > MAX_TEMPLATE_MEMBERS
    parameters = [_decode_parameter(p) for p in list(template.parameters)[:MAX_TEMPLATE_PARAMS]]
    return {
        "template": True,
        "template_ref": s(getattr(template, "template_ref", ""), 96),
        "is_definition": bool(template.is_definition),
        "version": s(getattr(template, "version", ""), 32),
        "members": members,
        "parameters": parameters,
        "metric_count": len(template.metrics),
        "members_truncated": members_truncated,
    }


def _metric_value(metric: Any, depth: int = 0) -> Any:
    """Extract a metric's scalar/complex value, JSON-safe, from the protobuf oneof.

    ``depth`` tracks Template nesting so recursively decoded Template members
    cannot recurse without bound (see :data:`MAX_TEMPLATE_DEPTH`).
    """
    which = metric.WhichOneof("value")
    if which is None:
        return None
    raw = getattr(metric, which)
    if which in ("int_value", "long_value"):
        return _reinterpret_signed(raw, metric.datatype)
    if which in ("float_value", "double_value", "boolean_value"):
        return raw
    if which == "string_value":
        return s(raw, 512)
    if which == "bytes_value":
        return {"bytes": len(raw), "hex_preview": raw[:32].hex()}
    if which == "dataset_value":
        return _decode_dataset(raw)
    if which == "template_value":
        return _decode_template(raw, depth)
    return s(str(raw), 256)


def _decode_metric(metric: Any, alias_map: dict[int, str]) -> dict:
    """Decode one Sparkplug B metric to a structured, JSON-safe descriptor."""
    name = metric.name or alias_map.get(metric.alias, "")
    has_alias = bool(metric.alias) or (not metric.name and metric.alias == 0)
    return {
        "name": s(name, 96),
        "alias": int(metric.alias) if metric.HasField("alias") else None,
        "datatype": _DATATYPE_NAMES.get(int(metric.datatype), str(int(metric.datatype))),
        "value": None if metric.is_null else _metric_value(metric),
        "timestamp": int(metric.timestamp) if metric.HasField("timestamp") else None,
        "is_historical": bool(metric.is_historical),
        "is_null": bool(metric.is_null),
        "_has_alias": has_alias,
    }


def decode_sparkplug_payload(payload: bytes, alias_map: dict[int, str] | None = None) -> dict:
    """Decode a raw Sparkplug B protobuf payload to a structured descriptor.

    ``alias_map`` (alias→name, built from a prior NBIRTH/DBIRTH) lets NDATA/DDATA
    metrics that carry only an alias be resolved to their names. Returns a clear
    error dict if protobuf is unavailable or the payload is not valid SpB.
    """
    pb = _sparkplug_pb()
    if pb is None:
        return {
            "encoding": "binary",
            "bytes": len(payload),
            "hex_preview": payload[:32].hex(),
            "error": "protobuf not available to decode Sparkplug B. "
            "Install the connector: 'pip install iaiops[sparkplug]'.",
        }
    aliases = alias_map or {}
    try:
        msg = pb.Payload()
        msg.ParseFromString(payload)
    except Exception as exc:  # noqa: BLE001 — malformed payload is not our crash
        return {
            "encoding": "binary",
            "bytes": len(payload),
            "hex_preview": payload[:32].hex(),
            "error": s(f"Not a valid Sparkplug B payload: {exc}", 160),
        }
    metrics = [_decode_metric(m, aliases) for m in list(msg.metrics)[:MAX_METRICS]]
    for m in metrics:
        m.pop("_has_alias", None)
    return {
        "encoding": "sparkplug_b",
        "timestamp": int(msg.timestamp) if msg.HasField("timestamp") else None,
        "seq": int(msg.seq) if msg.HasField("seq") else None,
        "uuid": s(msg.uuid, 64) if msg.uuid else "",
        "metric_count": len(metrics),
        "historical_count": sum(1 for m in metrics if m["is_historical"]),
        "metrics": metrics,
    }


def _decode_payload(payload: bytes) -> dict:
    """Best-effort decode of a plain-MQTT payload to a JSON-safe descriptor."""
    if not payload:
        return {"encoding": "empty"}
    text: str | None = None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None:
        stripped = text.strip()
        if stripped[:1] in ("{", "["):
            try:
                return {"encoding": "json", "json": json.loads(stripped)}
            except json.JSONDecodeError:
                pass
        if text.isprintable():
            return {"encoding": "text", "text": s(text, 512)}
    decoded = decode_sparkplug_payload(payload)
    if decoded.get("encoding") == "sparkplug_b":
        return decoded
    return {
        "encoding": "binary",
        "bytes": len(payload),
        "hex_preview": payload[:32].hex(),
        "note": "Binary payload that is not valid Sparkplug B / UTF-8.",
    }


def _parse_sparkplug_topic(topic: str) -> dict | None:
    """Parse a Sparkplug B topic into its components, or None if not Sparkplug."""
    parts = topic.split("/")
    if len(parts) >= 3 and parts[0].lower().startswith("spbv"):
        # STATE topics are spBv1.0/STATE/<host_id> (3 parts, no edge node).
        if len(parts) >= 2 and parts[1].upper() == "STATE":
            return {
                "namespace": s(parts[0], 16),
                "group_id": "",
                "message_type": "STATE",
                "edge_node_id": "",
                "device_id": "",
                "host_id": s(parts[2], 96) if len(parts) > 2 else "",
            }
        if len(parts) >= 4:
            return {
                "namespace": s(parts[0], 16),
                "group_id": s(parts[1], 64),
                "message_type": s(parts[2], 16),
                "edge_node_id": s(parts[3], 96),
                "device_id": s(parts[4], 96) if len(parts) > 4 else "",
                "host_id": "",
            }
    return None


# ─── birth/death + seq model ─────────────────────────────────────────────────


class _SparkplugModel:
    """Stateful Sparkplug B session model applied over messages in arrival order.

    Tracks, per edge node (and per device), the alias→name map (from BIRTH),
    online/offline state (BIRTH/DEATH), and seq continuity (gap / out-of-order).
    Also records primary-host STATE announcements.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.hosts: dict[str, dict] = {}

    @staticmethod
    def _node_key(parsed: dict) -> str:
        return f"{parsed['group_id']}/{parsed['edge_node_id']}"

    def _node(self, parsed: dict) -> dict:
        return self.nodes.setdefault(
            self._node_key(parsed),
            {
                "group_id": parsed["group_id"],
                "edge_node_id": parsed["edge_node_id"],
                "devices": set(),
                "online": False,
                "born": False,
                "alias_map": {},
                "last_seq": None,
                "seq_issues": [],
            },
        )

    def apply(self, topic: str, payload: bytes) -> dict | None:
        """Apply one message; return its decoded sample descriptor (or None)."""
        parsed = _parse_sparkplug_topic(topic)
        if not parsed:
            return None
        mtype = parsed["message_type"].upper()
        if mtype == "STATE":
            self.hosts[parsed["host_id"]] = {
                "host_id": parsed["host_id"],
                "state": s(_state_payload(payload), 32),
            }
            return {
                "topic": s(topic, 128),
                "sparkplug": parsed,
                "payload": {
                    "encoding": "state",
                    "host_id": parsed["host_id"],
                    "state": s(_state_payload(payload), 32),
                },
            }

        node = self._node(parsed)
        decoded = decode_sparkplug_payload(payload, node["alias_map"])

        if mtype in ("NBIRTH", "DBIRTH"):
            node["online"] = True
            node["born"] = True
            if mtype == "NBIRTH":
                node["alias_map"] = {}
                # Per the Sparkplug spec an NBIRTH restarts the node's seq at 0;
                # reset tracking so the rebirth is not flagged as a false gap.
                node["last_seq"] = None
            self._learn_aliases(node, payload)
            decoded = decode_sparkplug_payload(payload, node["alias_map"])
            if parsed["device_id"]:
                node["devices"].add(parsed["device_id"])
        elif mtype in ("NDEATH", "DDEATH"):
            if mtype == "NDEATH":
                node["online"] = False
            if parsed["device_id"]:
                node["devices"].add(parsed["device_id"])
        elif parsed["device_id"]:
            node["devices"].add(parsed["device_id"])

        self._track_seq(node, decoded.get("seq"), topic)
        return {"topic": s(topic, 128), "sparkplug": parsed, "payload": decoded}

    def _learn_aliases(self, node: dict, payload: bytes) -> None:
        """Build the alias→name map from a BIRTH payload's metrics."""
        pb = _sparkplug_pb()
        if pb is None:
            return
        try:
            msg = pb.Payload()
            msg.ParseFromString(payload)
        except Exception:  # noqa: BLE001 — malformed BIRTH is not fatal
            return
        for m in list(msg.metrics)[:MAX_METRICS]:
            if m.name and m.HasField("alias"):
                node["alias_map"][int(m.alias)] = m.name

    def _track_seq(self, node: dict, seq: int | None, topic: str) -> None:
        """Flag a seq gap / out-of-order against the node's expected counter."""
        if seq is None:
            return
        last = node["last_seq"]
        if last is not None:
            expected = (last + 1) % _SEQ_MOD
            if seq != expected:
                node["seq_issues"].append(
                    {"topic": s(topic, 96), "expected": expected, "got": int(seq)}
                )
        node["last_seq"] = int(seq)

    def node_summaries(self) -> list[dict]:
        return [
            {
                "group_id": n["group_id"],
                "edge_node_id": n["edge_node_id"],
                "online": n["online"],
                "born": n["born"],
                "devices": sorted(n["devices"]),
                "metric_aliases_known": len(n["alias_map"]),
                "seq_gap_count": len(n["seq_issues"]),
                "seq_issues": n["seq_issues"][:20],
            }
            for n in self.nodes.values()
        ]

    def host_summaries(self) -> list[dict]:
        return list(self.hosts.values())


def _state_payload(payload: bytes) -> str:
    """Decode a STATE payload (ONLINE/OFFLINE, plain or JSON ``{online:bool}``)."""
    try:
        text = payload.decode("utf-8").strip()
    except UnicodeDecodeError:
        return "unknown"
    if text[:1] == "{":
        try:
            obj = json.loads(text)
            return "ONLINE" if obj.get("online") else "OFFLINE"
        except json.JSONDecodeError:
            return s(text, 32)
    return s(text, 32) or "unknown"


# ─── tools ───────────────────────────────────────────────────────────────────


def mqtt_read_topic(
    target: Any, topic: str = "", count: int = DEFAULT_MESSAGES, timeout_s: int = DEFAULT_TIMEOUT_S
) -> dict:
    """[READ] Plain MQTT: collect a BOUNDED set of messages from a topic filter."""
    msgs = _collect(target, topic, count, timeout_s)
    return {
        "endpoint": s(target.name, 64),
        "topic": s(topic or getattr(target, "topic", "") or "#", 128),
        "message_count": len(msgs),
        "messages": [
            {"topic": s(m["topic"], 128), "payload": _decode_payload(m["payload"])} for m in msgs
        ],
    }


def sparkplug_subscribe_sample(
    target: Any, topic: str = "", count: int = DEFAULT_MESSAGES, timeout_s: int = DEFAULT_TIMEOUT_S
) -> dict:
    """[READ] Bounded Sparkplug B sample with full decode + birth/death + seq model."""
    topic = topic or getattr(target, "topic", "") or "spBv1.0/#"
    msgs = _collect(target, topic, count, timeout_s)
    model = _SparkplugModel()
    samples: list[dict] = []
    historical = 0
    for m in msgs:
        sample = model.apply(m["topic"], m["payload"])
        if sample is None:
            sample = {
                "topic": s(m["topic"], 128),
                "sparkplug": None,
                "payload": _decode_payload(m["payload"]),
            }
        historical += sample["payload"].get("historical_count", 0) or 0
        samples.append(sample)
    seq_gaps = sum(n["seq_gap_count"] for n in model.node_summaries())
    return {
        "endpoint": s(target.name, 64),
        "topic": s(topic, 128),
        "message_count": len(samples),
        "historical_metric_count": historical,
        "seq_gap_count": seq_gaps,
        "samples": samples,
    }


def sparkplug_decode_payload(
    payload: str, encoding: str = "base64", alias_map: dict | None = None
) -> dict:
    """[READ] Decode a single raw Sparkplug B payload string to structured metrics.

    ``payload`` is the raw protobuf bytes encoded as ``base64`` (default) or
    ``hex``. ``alias_map`` optionally supplies a prior {alias: name} map so
    alias-only NDATA/DDATA metrics resolve to names.
    """
    raw = (payload or "").strip()
    try:
        if encoding == "hex":
            data = bytes.fromhex(raw)
        else:
            data = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as exc:
        return {"error": s(f"Could not decode '{encoding}' payload: {exc}", 160)}
    amap = {int(k): str(v) for k, v in (alias_map or {}).items()} if alias_map else {}
    return decode_sparkplug_payload(data, amap)


def sparkplug_node_list(
    target: Any, timeout_s: int = DEFAULT_TIMEOUT_S, count: int = MAX_MESSAGES
) -> dict:
    """[READ] Discover edge nodes / devices + online state + primary-host STATE.

    Builds the birth/death + seq model from observed BIRTH/DATA/DEATH/STATE
    topics in the window: each node reports online/born, its devices, how many
    metric aliases were learned, and any seq gaps; STATE topics surface
    primary-host status.
    """
    msgs = _collect(target, "spBv1.0/#", count, timeout_s)
    model = _SparkplugModel()
    for m in msgs:
        model.apply(m["topic"], m["payload"])
    return {
        "endpoint": s(target.name, 64),
        "node_count": len(model.nodes),
        "nodes": model.node_summaries(),
        "primary_hosts": model.host_summaries(),
        "note": "Discovered from observed BIRTH/DATA/DEATH/STATE topics within the "
        "time window. Re-run with a longer timeout_s if nodes publish infrequently.",
    }


def uns_browse(
    target: Any, topic: str = "#", timeout_s: int = DEFAULT_TIMEOUT_S, count: int = MAX_MESSAGES
) -> dict:
    """[READ] Browse the live topic tree (UNS) under a topic filter (bounded)."""
    msgs = _collect(target, topic, count, timeout_s)
    tree: dict[str, Any] = {}
    topics: set[str] = set()
    for m in msgs:
        topics.add(m["topic"])
        node = tree
        for seg in m["topic"].split("/")[:12]:
            node = node.setdefault(s(seg, 64), {})
    return {
        "endpoint": s(target.name, 64),
        "filter": s(topic, 128),
        "topic_count": len(topics),
        "topics": sorted(s(t, 128) for t in topics)[:MAX_MESSAGES],
        "tree": tree,
    }


def mqtt_publish(
    target: Any,
    topic: str,
    payload: str,
    *,
    qos: int = 0,
    retain: bool = False,
    dry_run: bool = True,
) -> dict:
    """[WRITE][HIGH RISK] Publish/command to an MQTT topic (off by default).

    OT-dangerous: an MQTT command (e.g. a Sparkplug NCMD/DCMD) can change a live
    control system and has no automatic inverse. Refuses to act unless
    ``dry_run`` is explicitly False. 未经授权勿对生产控制系统下发指令.
    """
    qos = max(0, min(int(qos), 2))
    if dry_run:
        return {
            "endpoint": s(target.name, 64),
            "topic": s(topic, 128),
            "dry_run": True,
            "would_publish_bytes": len(payload.encode("utf-8")),
            "qos": qos,
            "retain": bool(retain),
            "note": "Dry run — nothing published. Re-run with dry_run=False AND a "
            "recorded approver to send. A published command cannot be auto-undone. "
            "未经授权勿对生产控制系统下发指令.",
        }
    with mqtt_session(target) as client:
        info = client.publish(topic, payload=payload, qos=qos, retain=bool(retain))
        try:
            info.wait_for_publish(timeout=DEFAULT_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — best-effort confirmation
            pass
    return {
        "endpoint": s(target.name, 64),
        "topic": s(topic, 128),
        "dry_run": False,
        "published_bytes": len(payload.encode("utf-8")),
        "qos": qos,
        "retain": bool(retain),
        "applied": True,
    }


__all__ = [
    "mqtt_read_topic",
    "sparkplug_subscribe_sample",
    "sparkplug_decode_payload",
    "sparkplug_node_list",
    "uns_browse",
    "mqtt_publish",
    "decode_sparkplug_payload",
    "OTConnectionError",
]
