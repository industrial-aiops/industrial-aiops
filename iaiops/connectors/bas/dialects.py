"""BAS vendor dialects — resource paths + field aliases per supervisory controller.

A *dialect* is the only thing that differs between the two supported vendor
controller REST surfaces. It is pure data (a frozen dataclass) plus two pure
functions (:func:`normalize_point`, :func:`normalize_alarm`, :func:`normalize_sample`)
that fold a vendor-shaped JSON object into the connector's neutral schema:

    point  -> {id, name, value, unit, status}
    alarm  -> {id, name, priority, state, message, timestamp}
    sample -> {timestamp, value}

Keeping the vendor knowledge in data (not code branches) means adding a third
controller later is a new :class:`BasDialect` row, not new logic. Vendor names
live ONLY here and in the edition tool/skill (never in core/brain or the base
README) per the brand-isolation iron rule.

The exact live write/trend resource semantics of each controller are 待核实
(the in-repo mock controller in ``tests/test_bas.py`` is the self-test); the
paths below follow each vendor's documented REST/oBIX resource tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Life-safety object name/id fragments that ``bas_command`` refuses OUTRIGHT.
# A supervisory command must never touch fire/smoke/egress/stair-pressurization
# equipment — those are life-safety systems governed by separate codes, never a
# BMS setpoint nudge. Matched case-insensitively as substrings of the point
# id AND name, so both "SmokeDamper-3" and "AHU/EGRESS_PRESS" are caught.
LIFE_SAFETY_DENY: tuple[str, ...] = (
    "fire",
    "smoke",
    "egress",
    "pressuriz",  # pressurization / pressurisation
    "stairwell",
    "stair-press",
    "sprinkler",
    "life-safety",
    "lifesafety",
    "life_safety",
)


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present, non-None value among ``keys`` in ``obj``."""
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


@dataclass(frozen=True)
class BasDialect:
    """Immutable per-vendor resource-path + field-alias map.

    ``*_path`` are request paths appended to the controller base URL; templates
    carry ``{id}`` for the point-scoped resources. ``*_fields`` are ordered
    candidate keys probed in turn when reading a value out of a vendor object
    (the first present wins). ``list_key`` names the array wrapper in a
    collection response (``None`` ⇒ the response body *is* the array).
    ``value_container`` optionally descends one level before reading a single
    object's fields (e.g. Metasys wraps attributes under ``item``).
    """

    name: str
    points_path: str
    point_path: str  # template with {id}
    alarms_path: str
    trend_path: str  # template with {id}
    command_path: str  # template with {id}
    write_value_field: str
    id_fields: tuple[str, ...]
    name_fields: tuple[str, ...]
    value_fields: tuple[str, ...]
    unit_fields: tuple[str, ...] = ()
    status_fields: tuple[str, ...] = ()
    priority_fields: tuple[str, ...] = ()
    state_fields: tuple[str, ...] = ()
    message_fields: tuple[str, ...] = ()
    timestamp_fields: tuple[str, ...] = ()
    list_key: str | None = None
    value_container: str | None = None
    sample_value_fields: tuple[str, ...] = ()
    sample_time_fields: tuple[str, ...] = ()
    # Accept header the controller needs for JSON (oBIX defaults to XML).
    accept: str = "application/json"

    def items(self, payload: Any) -> list[dict[str, Any]]:
        """Extract the list of objects from a collection response body."""
        if self.list_key is not None and isinstance(payload, dict):
            payload = payload.get(self.list_key, [])
        if isinstance(payload, list):
            return [o for o in payload if isinstance(o, dict)]
        return []

    def unwrap(self, payload: Any) -> dict[str, Any]:
        """Descend into ``value_container`` for a single-object response."""
        if isinstance(payload, dict) and self.value_container:
            inner = payload.get(self.value_container)
            if isinstance(inner, dict):
                return inner
        return payload if isinstance(payload, dict) else {}


# ── Vendor rows ───────────────────────────────────────────────────────────────
# Johnson Controls Metasys (OpenBlue) REST API — /objects tree, JSON everywhere.
_METASYS = BasDialect(
    name="metasys",
    points_path="/objects",
    point_path="/objects/{id}",
    alarms_path="/alarms",
    trend_path="/objects/{id}/trendedAttributes/presentValue/samples",
    command_path="/objects/{id}/attributes/presentValue",
    write_value_field="value",
    id_fields=("id", "objectId"),
    name_fields=("itemReference", "name"),
    value_fields=("presentValue", "value"),
    unit_fields=("units", "unit"),
    status_fields=("status", "reliability"),
    priority_fields=("priority",),
    state_fields=("type", "isAckRequired", "state"),
    message_fields=("message", "name", "itemReference"),
    timestamp_fields=("creationTime", "timestamp"),
    list_key="items",
    value_container="item",
    sample_value_fields=("value", "presentValue"),
    sample_time_fields=("timestamp", "time"),
)

# Tridium Niagara 4 — oBIX/REST resource tree. Modelled as JSON-over-REST
# (Accept: application/json); native oBIX XML encoding is 待核实.
_NIAGARA = BasDialect(
    name="niagara",
    points_path="/obix/config/points/",
    point_path="/obix/{id}/",
    alarms_path="/obix/alarms/",
    trend_path="/obix/histories/{id}/",
    command_path="/obix/{id}/set/",
    write_value_field="in",
    id_fields=("href", "name"),
    name_fields=("displayName", "name"),
    value_fields=("val", "value"),
    unit_fields=("unit", "facets"),
    status_fields=("status",),
    priority_fields=("priority",),
    state_fields=("alarmState", "ackState", "status"),
    message_fields=("msgText", "displayName", "name"),
    timestamp_fields=("timestamp", "normalTime"),
    list_key="children",
    value_container=None,
    sample_value_fields=("value", "val"),
    sample_time_fields=("timestamp", "time"),
)

DIALECTS: dict[str, BasDialect] = {"metasys": _METASYS, "niagara": _NIAGARA}
VENDORS: tuple[str, ...] = tuple(DIALECTS)


class UnknownVendorError(ValueError):
    """Raised when a caller names a BAS vendor with no registered dialect."""


def get_dialect(vendor: str) -> BasDialect:
    """Resolve a dialect by vendor key, teaching on an unknown vendor."""
    key = (vendor or "").strip().lower()
    try:
        return DIALECTS[key]
    except KeyError as exc:
        raise UnknownVendorError(
            f"Unknown BAS vendor '{vendor}'. Supported: {', '.join(VENDORS)}."
        ) from exc


def is_life_safety(point_id: str, point_name: str = "") -> str:
    """Return the matched life-safety keyword if the point is denied, else ''.

    Matched case-insensitively as a substring of the id and the name, so any
    fire / smoke / egress / (stair-)pressurization / sprinkler point is refused.
    """
    hay = f"{point_id or ''} {point_name or ''}".lower()
    for keyword in LIFE_SAFETY_DENY:
        if keyword in hay:
            return keyword
    return ""


# ── Normalization (pure; the heart of the dialect abstraction) ────────────────
def normalize_point(raw: dict[str, Any], dialect: BasDialect) -> dict[str, Any]:
    """Fold a vendor point object into ``{id, name, value, unit, status}``."""
    obj = dialect.unwrap(raw)
    # id/name may live on the outer object even when values are wrapped.
    outer = raw if isinstance(raw, dict) else {}
    return {
        "id": _first(outer, dialect.id_fields) or _first(obj, dialect.id_fields),
        "name": _first(outer, dialect.name_fields) or _first(obj, dialect.name_fields),
        "value": _first(obj, dialect.value_fields),
        "unit": _first(obj, dialect.unit_fields),
        "status": _first(obj, dialect.status_fields),
    }


def normalize_alarm(raw: dict[str, Any], dialect: BasDialect) -> dict[str, Any]:
    """Fold a vendor alarm/event object into the neutral alarm schema."""
    return {
        "id": _first(raw, dialect.id_fields),
        "name": _first(raw, dialect.name_fields),
        "priority": _first(raw, dialect.priority_fields),
        "state": _first(raw, dialect.state_fields),
        "message": _first(raw, dialect.message_fields),
        "timestamp": _first(raw, dialect.timestamp_fields),
    }


def normalize_sample(raw: dict[str, Any], dialect: BasDialect) -> dict[str, Any]:
    """Fold a vendor trend sample into ``{timestamp, value}``."""
    return {
        "timestamp": _first(raw, dialect.sample_time_fields),
        "value": _first(raw, dialect.sample_value_fields),
    }


__all__ = [
    "BasDialect",
    "DIALECTS",
    "LIFE_SAFETY_DENY",
    "UnknownVendorError",
    "VENDORS",
    "get_dialect",
    "is_life_safety",
    "normalize_alarm",
    "normalize_point",
    "normalize_sample",
]
