"""IODD → a DRAFT sensor profile (HLD §16.3 rule 2).

An IODD is the XML a vendor publishes for an IO-Link device. Reading its
process-data layout is deterministic — no model is involved — but the result is
still a draft, not a fact: it is marked ``source: iodd, verified: 待核实`` until
a live reading has been checked against it.

What is taken from the IODD: device identity (→ ``match``), each process-data-in
record item's bit offset / length / type, the UI gradient and offset (→ scale /
offset), ``ValueRange`` (→ the engineering range) and named ``SingleValue``s that
lie OUTSIDE that range (→ sentinels; a named value inside the range is an
ordinary measurement with a label).

What is NOT guessed: units (IODD unit codes are kept as codes and marked
待核实), signal kind (assumed ``level`` for numbers and ``event`` for booleans,
and said so), and anything the profile cannot represent — listed in ``notes``,
never dropped in silence.

Parsing uses stdlib ``xml.etree`` with the same hardening as the L5X parser: a
document that declares a DTD or entities is refused before it reaches the parser
(``defusedxml`` is not a dependency), and the file size is capped.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 — DTD/entity rejection before parsing
from dataclasses import dataclass, field
from typing import Any

MAX_IODD_BYTES = 10 * 1024 * 1024
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
_FORBIDDEN = ("<!DOCTYPE", "<!ENTITY")
_NUMERIC = {"UIntegerT": "uint", "IntegerT": "int", "Float32T": "float", "BooleanT": "uint"}


@dataclass(frozen=True)
class IoddDraft:
    """A draft profile mapping, plus what could not be imported."""

    profile: dict[str, Any]
    device_name: str = ""
    notes: tuple[str, ...] = field(default=())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element | None, name: str) -> ET.Element | None:
    if elem is None:
        return None
    return next((c for c in elem if _local(c.tag) == name), None)


def _children(elem: ET.Element | None, name: str) -> list[ET.Element]:
    return [] if elem is None else [c for c in elem if _local(c.tag) == name]


def _descend(elem: ET.Element | None, *path: str) -> ET.Element | None:
    for name in path:
        elem = _child(elem, name)
    return elem


def _parse_xml(text: str) -> ET.Element:
    if len(text.encode("utf-8")) > MAX_IODD_BYTES:
        raise ValueError(f"IODD is larger than {MAX_IODD_BYTES // (1024 * 1024)} MB — refused.")
    upper = text.upper()
    for marker in _FORBIDDEN:
        if marker in upper:
            raise ValueError(
                f"IODD refused: it contains '{marker}'. DTD/entity declarations are not "
                "allowed (XXE hardening)."
            )
    try:
        root = ET.fromstring(text)  # noqa: S314 — DTD/entities rejected above  # nosec B314
    except ET.ParseError as exc:
        raise ValueError(f"IODD is not well-formed XML: {exc}") from exc
    if _local(root.tag) != "IODevice":
        raise ValueError(f"Not an IODD: the root element is {_local(root.tag)!r}, not IODevice.")
    return root


def _texts(root: ET.Element) -> dict[str, str]:
    language = _descend(root, "ExternalTextCollection", "PrimaryLanguage")
    return {t.get("id", ""): t.get("value", "") for t in _children(language, "Text")}


def _int_attr(elem: ET.Element, name: str, what: str) -> int:
    try:
        return int(elem.get(name, ""))
    except ValueError as exc:
        raise ValueError(f"IODD {what} has no integer {name!r}.") from exc


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _select_process_data(root: ET.Element, choice: str | None) -> ET.Element:
    collection = _descend(root, "ProfileBody", "DeviceFunction", "ProcessDataCollection")
    variants = _children(collection, "ProcessData")
    if not variants:
        raise ValueError("IODD has no ProcessData — nothing to collect from this device.")
    ids = [v.get("id", "?") for v in variants]
    if choice is not None:
        for variant in variants:
            if variant.get("id") == choice:
                return variant
        raise ValueError(f"IODD has no ProcessData {choice!r}. Present: {', '.join(ids)}.")
    if len(variants) > 1:
        raise ValueError(
            f"IODD declares several process-data layouts ({', '.join(ids)}) — which one is "
            "active depends on the device's configuration. Choose one with --process-data."
        )
    return variants[0]


def _ui_info(root: ET.Element, pd_in_id: str) -> dict[str, ET.Element]:
    refs = _descend(root, "ProfileBody", "UserInterface", "ProcessDataRefCollection")
    for ref in _children(refs, "ProcessDataRef"):
        if ref.get("processDataId") == pd_in_id:
            return {i.get("subindex", ""): i for i in _children(ref, "ProcessDataRecordItemInfo")}
    return {}


class _Context:
    """Lookups shared by every record item of one IODD."""

    def __init__(self, root: ET.Element, pd_in_id: str) -> None:
        self.texts = _texts(root)
        collection = _descend(root, "ProfileBody", "DeviceFunction", "DatatypeCollection")
        self.datatypes = {d.get("id", ""): d for d in _children(collection, "Datatype")}
        self.ui = _ui_info(root, pd_in_id)
        self.notes: list[str] = []
        self.names: set[str] = set()

    def text(self, elem: ET.Element | None) -> str:
        name = _child(elem, "Name")
        return self.texts.get(name.get("textId", ""), "") if name is not None else ""

    def datatype(self, holder: ET.Element) -> ET.Element | None:
        ref = _child(holder, "DatatypeRef")
        if ref is not None:
            return self.datatypes.get(ref.get("datatypeId", ""))
        # Not `a or b`: an Element with no children is falsy.
        simple = _child(holder, "SimpleDatatype")
        return simple if simple is not None else _child(holder, "Datatype")

    def unique(self, label: str, fallback: str) -> str:
        base = _slug(label) or fallback
        name, n = base, 2
        while name in self.names:
            name, n = f"{base}_{n}", n + 1
        self.names.add(name)
        return name


def _raw_of(value: float, kind: str, length: int) -> int:
    """A SingleValue as the raw unsigned field (two's complement for signed)."""
    raw = int(value)
    return raw & ((1 << length) - 1) if kind == "int" else raw


def _range_and_sentinels(
    dtype: ET.Element,
    kind: str,
    length: int,
    scale: float,
    offset: float,
    label: str,
    ctx: _Context,
) -> tuple[list[float] | None, list[dict[str, Any]]]:
    if kind == "uint" and length == 1:
        return None, []  # a boolean's named values are its two states
    span = _child(dtype, "ValueRange")
    low = _number(span.get("lowerValue")) if span is not None else None
    high = _number(span.get("upperValue")) if span is not None else None
    singles = [(v.get("value"), ctx.text(v)) for v in _children(dtype, "SingleValue")]
    if low is None or high is None:
        if singles:
            ctx.notes.append(
                f"{label}: {len(singles)} named value(s) not mapped — without a ValueRange "
                "they cannot be told apart from measurements."
            )
        return None, []
    sentinels = []
    for raw_text, meaning in singles:
        raw = _number(raw_text)
        if raw is None:
            continue
        if low <= raw <= high:
            continue  # a labelled measurement, not a sentinel
        if kind == "float":
            ctx.notes.append(f"{label}: float sentinel {raw_text} ({meaning}) not mapped.")
            continue
        sentinels.append(
            {"raw": _raw_of(raw, kind, length), "meaning": meaning or f"code {raw_text}"}
        )
    ends = sorted((round(low * scale + offset, 9), round(high * scale + offset, 9)))
    if ends[0] == ends[1]:
        ctx.notes.append(f"{label}: ValueRange is a single value — range not set.")
        return None, sentinels
    return [ends[0], ends[1]], sentinels


def _channel(
    item: ET.Element | None, holder: ET.Element, bit_offset: int, ctx: _Context
) -> dict | None:
    label = ctx.text(item if item is not None else holder) or "process data"
    subindex = item.get("subindex", "") if item is not None else ""
    dtype = ctx.datatype(item if item is not None else holder)
    type_name = dtype.get(_XSI_TYPE, "") if dtype is not None else ""
    kind = _NUMERIC.get(type_name)
    if kind is None:
        ctx.notes.append(f"{label}: {type_name or 'unknown type'} is not a number — not imported.")
        return None
    length = 1 if type_name == "BooleanT" else _int_attr(dtype, "bitLength", f"item {label!r}")
    info = ctx.ui.get(subindex)
    scale = _number(info.get("gradient")) if info is not None else None
    offset = _number(info.get("offset")) if info is not None else None
    scale = scale if scale not in (None, 0.0) else 1.0
    offset = offset or 0.0
    code = info.get("unitCode") if info is not None else None
    if type_name == "BooleanT":
        unit = "bool"
    else:
        unit = f"unitCode {code} (待核实)" if code else "待核实"
    channel: dict[str, Any] = {
        "name": ctx.unique(label, f"item_{subindex or bit_offset}"),
        "layout": {"bit_offset": bit_offset, "bit_length": length, "type": kind},
    }
    if scale != 1.0:
        channel["scale"] = scale
    if offset != 0.0:
        channel["offset"] = offset
    channel["unit"] = unit
    value_range, sentinels = _range_and_sentinels(dtype, kind, length, scale, offset, label, ctx)
    if value_range is not None:
        channel["range"] = value_range
    if sentinels:
        channel["invalid"] = sentinels
    channel["signal"] = "event" if type_name == "BooleanT" else "level"
    return channel


def import_iodd(text: str, process_data: str | None = None) -> IoddDraft:
    """Parse an IODD's process-data-in into a draft profile mapping."""
    root = _parse_xml(text)
    identity = _descend(root, "ProfileBody", "DeviceIdentity")
    if identity is None:
        raise ValueError("IODD has no DeviceIdentity.")
    vendor = _int_attr(identity, "vendorId", "DeviceIdentity")
    device = _int_attr(identity, "deviceId", "DeviceIdentity")
    pd_in = _child(_select_process_data(root, process_data), "ProcessDataIn")
    if pd_in is None:
        raise ValueError("The selected ProcessData has no ProcessDataIn — nothing to read.")
    ctx = _Context(root, pd_in.get("id", ""))
    top = ctx.datatype(pd_in)
    if top is not None and top.get(_XSI_TYPE) == "RecordT":
        pairs = [
            (item, _int_attr(item, "bitOffset", "RecordItem"))
            for item in _children(top, "RecordItem")
        ]
        channels = [_channel(item, item, offset, ctx) for item, offset in pairs]
    else:
        channels = [_channel(None, pd_in, 0, ctx)]
    kept = [c for c in channels if c is not None]
    if not kept:
        raise ValueError("IODD process data has no numeric items to collect.")
    profile = {
        "id": f"iodd-{vendor}-{device}",
        "protocol": "iolink",
        "source": "iodd",
        "verified": "待核实",
        "match": {"vendor_id": vendor, "device_id": device},
        "channels": kept,
    }
    device_name = _child(identity, "DeviceName")
    name = ctx.texts.get(device_name.get("textId", ""), "") if device_name is not None else ""
    return IoddDraft(profile=profile, device_name=name, notes=tuple(ctx.notes))


def render_draft(draft: IoddDraft, source_name: str) -> str:
    """The draft as commented YAML: what was assumed, and what was left out."""
    import yaml

    from iaiops import __version__

    match = draft.profile["match"]
    header = [
        f"# DRAFT sensor profile imported from {source_name} (IODD) by iaiops {__version__}.",
        f"# Device: {draft.device_name or '?'} — "
        f"vendor {match['vendor_id']}, device {match['device_id']}.",
        "# verified: 待核实 until a live reading has been checked against this decoding.",
        "# Signal kinds were assumed, not read from the IODD:",
        "#   level for numbers, event for booleans.",
        "# Units are IODD unit codes, not mapped to symbols:",
        "#   replace each with the real unit.",
    ]
    if draft.notes:
        header.append("# Not imported:")
        header.extend(f"#   - {note}" for note in draft.notes)
    body = yaml.safe_dump(draft.profile, allow_unicode=True, sort_keys=False)
    return "\n".join(header) + "\n" + body


__all__ = ["MAX_IODD_BYTES", "IoddDraft", "import_iodd", "render_draft"]
