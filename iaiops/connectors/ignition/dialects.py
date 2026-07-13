"""Gateway HTTP dialects — resource paths + field aliases per API deployment.

A *dialect* is the only thing that differs between the supported Gateway HTTP
web-API deployment shapes. It is pure data (a frozen dataclass) plus four pure
functions that fold a vendor-shaped JSON object into the connector's neutral
schema:

    module  -> {name, state, version}
    node    -> {name, path, type, has_children}   (tag-tree browse)
    tag     -> {path, value, quality, timestamp}  (current value)
    alarm   -> {name, source, priority, state, label, timestamp}
    sample  -> {timestamp, value, quality}         (historian)

Keeping the deployment knowledge in data (not code branches) means adding a
third deployment layout later is a new :class:`IgnitionDialect` row, not new
logic. Vendor/product names live ONLY here and in the edition tool/skill (never
in core/brain or the base README) per the brand-isolation iron rule.

The exact live resource paths/field names of each deployment are 待核实 (the
in-repo mock Gateway in ``tests/test_ignition_tools.py`` is the self-test); the
paths below follow the platform's documented WebDev / system-function REST shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present, non-None value among ``keys`` in ``obj``."""
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


@dataclass(frozen=True)
class IgnitionDialect:
    """Immutable per-deployment resource-path + field-alias map (READ-ONLY).

    ``*_path`` are request paths appended to the Gateway base URL; templates
    carry ``{provider}`` / ``{path}`` / ``{start}`` / ``{end}`` placeholders for
    the scoped resources. ``*_fields`` are ordered candidate keys probed in turn
    when reading a value out of a JSON object (the first present wins).
    ``*_list_key`` names the array wrapper in a collection response (``None`` ⇒
    the response body *is* the array).
    """

    name: str
    status_path: str
    browse_path: str  # template with {provider} and {path}
    read_path: str  # template with {provider} and {path}
    alarms_path: str
    history_path: str  # template with {provider}, {path}, {start}, {end}, {count}
    # collection wrappers
    modules_list_key: str | None
    browse_list_key: str | None
    read_list_key: str | None
    alarms_list_key: str | None
    history_list_key: str | None
    # gateway status fields
    gateway_name_fields: tuple[str, ...]
    gateway_version_fields: tuple[str, ...]
    gateway_state_fields: tuple[str, ...]
    modules_container_fields: tuple[str, ...]
    module_name_fields: tuple[str, ...]
    module_state_fields: tuple[str, ...]
    module_version_fields: tuple[str, ...]
    # browse node fields
    node_name_fields: tuple[str, ...]
    node_path_fields: tuple[str, ...]
    node_type_fields: tuple[str, ...]
    node_children_fields: tuple[str, ...]
    # tag value fields
    tag_path_fields: tuple[str, ...]
    tag_value_fields: tuple[str, ...]
    tag_quality_fields: tuple[str, ...]
    tag_time_fields: tuple[str, ...]
    # alarm fields
    alarm_name_fields: tuple[str, ...]
    alarm_source_fields: tuple[str, ...]
    alarm_priority_fields: tuple[str, ...]
    alarm_state_fields: tuple[str, ...]
    alarm_label_fields: tuple[str, ...]
    alarm_time_fields: tuple[str, ...]
    # history sample fields
    sample_time_fields: tuple[str, ...]
    sample_value_fields: tuple[str, ...]
    sample_quality_fields: tuple[str, ...]
    accept: str = "application/json"

    def _items(self, payload: Any, list_key: str | None) -> list[dict[str, Any]]:
        """Extract the list of objects from a collection response body."""
        if list_key is not None and isinstance(payload, dict):
            payload = payload.get(list_key, [])
        if isinstance(payload, list):
            return [o for o in payload if isinstance(o, dict)]
        return []

    def modules(self, payload: Any) -> list[dict[str, Any]]:
        """Extract the modules array from a gateway-status body."""
        container: Any = payload
        if isinstance(payload, dict):
            for key in self.modules_container_fields:
                if isinstance(payload.get(key), list):
                    container = payload[key]
                    break
        return self._items(container, self.modules_list_key)

    def nodes(self, payload: Any) -> list[dict[str, Any]]:
        return self._items(payload, self.browse_list_key)

    def tags(self, payload: Any) -> list[dict[str, Any]]:
        return self._items(payload, self.read_list_key)

    def alarms(self, payload: Any) -> list[dict[str, Any]]:
        return self._items(payload, self.alarms_list_key)

    def samples(self, payload: Any) -> list[dict[str, Any]]:
        return self._items(payload, self.history_list_key)


# ── Deployment rows ───────────────────────────────────────────────────────────
# WebDev-module JSON endpoints — the common way the platform exposes system.tag.*
# and system.alarm.* over HTTP (one project namespace under /system/webdev).
_WEBDEV = IgnitionDialect(
    name="webdev",
    status_path="/system/webdev/iaiops/status",
    browse_path="/system/webdev/iaiops/tags/browse?provider={provider}&path={path}",
    read_path="/system/webdev/iaiops/tags/read?provider={provider}&paths={path}",
    alarms_path="/system/webdev/iaiops/alarms",
    history_path=(
        "/system/webdev/iaiops/tags/history?provider={provider}&path={path}"
        "&start={start}&end={end}&count={count}"
    ),
    modules_list_key=None,
    browse_list_key="tags",
    read_list_key="results",
    alarms_list_key="alarms",
    history_list_key="rows",
    gateway_name_fields=("gatewayName", "name", "systemName"),
    gateway_version_fields=("version", "platformVersion"),
    gateway_state_fields=("state", "status", "runningState"),
    modules_container_fields=("modules",),
    module_name_fields=("name", "moduleName"),
    module_state_fields=("state", "status"),
    module_version_fields=("version",),
    node_name_fields=("name", "tagName"),
    node_path_fields=("fullPath", "path"),
    node_type_fields=("tagType", "type", "valueType"),
    node_children_fields=("hasChildren", "isFolder"),
    tag_path_fields=("path", "tagPath", "fullPath"),
    tag_value_fields=("value", "val"),
    tag_quality_fields=("quality", "q"),
    tag_time_fields=("timestamp", "t"),
    alarm_name_fields=("name", "displayPath"),
    alarm_source_fields=("source", "sourcePath"),
    alarm_priority_fields=("priority",),
    alarm_state_fields=("state", "eventState"),
    alarm_label_fields=("label", "message", "displayPath"),
    alarm_time_fields=("timestamp", "eventTime", "activeTime"),
    sample_time_fields=("timestamp", "t"),
    sample_value_fields=("value", "v"),
    sample_quality_fields=("quality", "q"),
)

# Gateway status/system-function REST — alternate layout under /data/... with
# camelCase status envelopes (modules under 'moduleList'). Modelled as JSON-over-
# HTTP; the exact live path tree of this layout is 待核实.
_GATEWAY = IgnitionDialect(
    name="gateway",
    status_path="/data/status/gateway",
    browse_path="/data/tags/browse/{provider}/{path}",
    read_path="/data/tags/read/{provider}/{path}",
    alarms_path="/data/alarms/status",
    history_path="/data/tags/history/{provider}/{path}?start={start}&end={end}&count={count}",
    modules_list_key=None,
    browse_list_key="results",
    read_list_key="values",
    alarms_list_key="events",
    history_list_key="samples",
    gateway_name_fields=("name", "gatewayName"),
    gateway_version_fields=("version",),
    gateway_state_fields=("state", "activityLevel"),
    modules_container_fields=("moduleList", "modules"),
    module_name_fields=("moduleName", "name"),
    module_state_fields=("moduleState", "state"),
    module_version_fields=("moduleVersion", "version"),
    node_name_fields=("name",),
    node_path_fields=("fullPath", "path"),
    node_type_fields=("type", "objectType"),
    node_children_fields=("hasChildren",),
    tag_path_fields=("tagPath", "path"),
    tag_value_fields=("value",),
    tag_quality_fields=("qualityCode", "quality"),
    tag_time_fields=("timestamp",),
    alarm_name_fields=("displayPath", "name"),
    alarm_source_fields=("source",),
    alarm_priority_fields=("priority",),
    alarm_state_fields=("state",),
    alarm_label_fields=("label", "displayPath"),
    alarm_time_fields=("eventTime", "timestamp"),
    sample_time_fields=("timestamp",),
    sample_value_fields=("value",),
    sample_quality_fields=("qualityCode", "quality"),
)

DIALECTS: dict[str, IgnitionDialect] = {"webdev": _WEBDEV, "gateway": _GATEWAY}
FLAVORS: tuple[str, ...] = tuple(DIALECTS)


class UnknownFlavorError(ValueError):
    """Raised when a caller names a Gateway API flavor with no registered dialect."""


def get_dialect(flavor: str) -> IgnitionDialect:
    """Resolve a dialect by deployment-flavor key, teaching on an unknown flavor."""
    key = (flavor or "").strip().lower()
    try:
        return DIALECTS[key]
    except KeyError as exc:
        raise UnknownFlavorError(
            f"Unknown Gateway API flavor '{flavor}'. Supported: {', '.join(FLAVORS)}."
        ) from exc


# ── Normalization (pure; the heart of the dialect abstraction) ────────────────
def normalize_module(raw: dict[str, Any], dialect: IgnitionDialect) -> dict[str, Any]:
    """Fold a module-status object into ``{name, state, version}``."""
    return {
        "name": _first(raw, dialect.module_name_fields),
        "state": _first(raw, dialect.module_state_fields),
        "version": _first(raw, dialect.module_version_fields),
    }


def normalize_node(raw: dict[str, Any], dialect: IgnitionDialect) -> dict[str, Any]:
    """Fold a tag-tree node into ``{name, path, type, has_children}``."""
    return {
        "name": _first(raw, dialect.node_name_fields),
        "path": _first(raw, dialect.node_path_fields),
        "type": _first(raw, dialect.node_type_fields),
        "has_children": bool(_first(raw, dialect.node_children_fields)),
    }


def normalize_tag(raw: dict[str, Any], dialect: IgnitionDialect) -> dict[str, Any]:
    """Fold a current-value object into ``{path, value, quality, timestamp}``."""
    return {
        "path": _first(raw, dialect.tag_path_fields),
        "value": _first(raw, dialect.tag_value_fields),
        "quality": _first(raw, dialect.tag_quality_fields),
        "timestamp": _first(raw, dialect.tag_time_fields),
    }


def normalize_alarm(raw: dict[str, Any], dialect: IgnitionDialect) -> dict[str, Any]:
    """Fold an alarm-status object into the neutral alarm schema."""
    return {
        "name": _first(raw, dialect.alarm_name_fields),
        "source": _first(raw, dialect.alarm_source_fields),
        "priority": _first(raw, dialect.alarm_priority_fields),
        "state": _first(raw, dialect.alarm_state_fields),
        "label": _first(raw, dialect.alarm_label_fields),
        "timestamp": _first(raw, dialect.alarm_time_fields),
    }


def normalize_sample(raw: dict[str, Any], dialect: IgnitionDialect) -> dict[str, Any]:
    """Fold a historian sample into ``{timestamp, value, quality}``."""
    return {
        "timestamp": _first(raw, dialect.sample_time_fields),
        "value": _first(raw, dialect.sample_value_fields),
        "quality": _first(raw, dialect.sample_quality_fields),
    }


def normalize_gateway(raw: dict[str, Any], dialect: IgnitionDialect) -> dict[str, Any]:
    """Fold the gateway-status envelope into ``{name, version, state}`` (modules apart)."""
    obj = raw if isinstance(raw, dict) else {}
    return {
        "name": _first(obj, dialect.gateway_name_fields),
        "version": _first(obj, dialect.gateway_version_fields),
        "state": _first(obj, dialect.gateway_state_fields),
    }


__all__ = [
    "DIALECTS",
    "FLAVORS",
    "IgnitionDialect",
    "UnknownFlavorError",
    "get_dialect",
    "normalize_alarm",
    "normalize_gateway",
    "normalize_module",
    "normalize_node",
    "normalize_sample",
    "normalize_tag",
]
