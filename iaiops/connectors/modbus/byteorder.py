"""Modbus byte/word-order auto-detection (pure decode logic, no device needed).

Raw Modbus registers are untyped 16-bit words; multi-register numerics (uint32 /
int32 / float32) can be laid out in any of four common word/byte orders, and
single-register 16-bit numerics in either of two. Which one a given PLC/meter
uses is device-specific and a recurring community pain point (R4): the same
register block decodes to wildly different values per order.

This module decodes a raw register array under every candidate order for the
requested numeric type and SCORES the candidates against a plausibility signal
(an expected ``hint`` value and/or an in-range ``[value_min, value_max]`` band),
returning the most likely order. It is PURE — it never touches a device — so it
is fully unit-testable.

Order names follow the common industrial convention (bytes of a 32-bit value
``A B C D`` where ``A`` is the most-significant):

  * ``ABCD`` — big-endian (high word first, big-endian bytes).
  * ``DCBA`` — little-endian (full reversal).
  * ``BADC`` — byte-swapped (swap bytes within each word, word order kept).
  * ``CDAB`` — word-swapped / "mid-little" (swap the two words, bytes kept).

16-bit types use ``AB`` (big-endian) and ``BA`` (byte-swapped).
"""

from __future__ import annotations

import struct
from typing import Any

# Numeric types this detector understands → (register count, is_float, is_signed).
_TYPE_WIDTH: dict[str, int] = {
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
}

# Candidate word/byte orders per width (in bytes: width*2).
_ORDERS_16 = ("AB", "BA")
_ORDERS_32 = ("ABCD", "DCBA", "BADC", "CDAB")

# How each order maps source bytes (A,B[,C,D]) to the big-endian byte sequence
# that ``struct`` then unpacks. Index into (A, B) or (A, B, C, D).
_ORDER_MAP: dict[str, tuple[int, ...]] = {
    "AB": (0, 1),
    "BA": (1, 0),
    "ABCD": (0, 1, 2, 3),
    "DCBA": (3, 2, 1, 0),
    "BADC": (1, 0, 3, 2),
    "CDAB": (2, 3, 0, 1),
}


def supported_types() -> tuple[str, ...]:
    """Return the numeric types this detector can resolve."""
    return tuple(_TYPE_WIDTH)


def orders_for(value_type: str) -> tuple[str, ...]:
    """Return the candidate order names for a numeric type."""
    return _ORDERS_16 if _TYPE_WIDTH.get(value_type, 2) == 1 else _ORDERS_32


def _source_bytes(registers: list[int], width: int) -> bytes:
    """Big-endian bytes of the first ``width`` registers (each a 16-bit word)."""
    words = [int(r) & 0xFFFF for r in registers[:width]]
    return struct.pack(f">{len(words)}H", *words)


def decode_value(registers: list[int], value_type: str, order: str) -> float | int:
    """Decode the first numeric of ``value_type`` from ``registers`` under ``order``.

    Pure: raises ``ValueError`` for an unknown type/order or too-few registers.
    """
    if value_type not in _TYPE_WIDTH:
        raise ValueError(
            f"Unknown value_type {value_type!r}. Supported: {', '.join(supported_types())}."
        )
    width = _TYPE_WIDTH[value_type]
    if len(registers) < width:
        raise ValueError(
            f"value_type {value_type!r} needs {width} register(s); got {len(registers)}."
        )
    mapping = _ORDER_MAP.get(order)
    if mapping is None or len(mapping) != width * 2:
        raise ValueError(f"Order {order!r} is not valid for value_type {value_type!r}.")
    src = _source_bytes(registers, width)
    reordered = bytes(src[i] for i in mapping)
    if value_type == "uint16":
        return struct.unpack(">H", reordered)[0]
    if value_type == "int16":
        return struct.unpack(">h", reordered)[0]
    if value_type == "uint32":
        return struct.unpack(">I", reordered)[0]
    if value_type == "int32":
        return struct.unpack(">i", reordered)[0]
    return round(struct.unpack(">f", reordered)[0], 6)  # float32


def _in_range(value: float, value_min: float | None, value_max: float | None) -> bool:
    """True if ``value`` falls within the (optional) inclusive band."""
    if value_min is not None and value < value_min:
        return False
    return not (value_max is not None and value > value_max)


def detect_byte_order(
    registers: list[int],
    value_type: str = "float32",
    *,
    hint: float | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
) -> dict[str, Any]:
    """Score every candidate order for ``value_type`` against a plausibility signal.

    Provide a ``hint`` (a known/expected sample value), a ``[value_min, value_max]``
    band, or both. Each candidate order is decoded; a candidate is *valid* when it
    falls in the band (if one was given). The best pick is the valid candidate
    closest to the hint (or the sole in-range one). Confidence reflects how clear
    that choice is. PURE — no device access.

    Returns a dict with ``candidates`` (every order + decoded value + flags),
    ``best`` (the chosen order or ``None``), ``confidence`` and a ``note``.
    """
    if value_type not in _TYPE_WIDTH:
        raise ValueError(
            f"Unknown value_type {value_type!r}. Supported: {', '.join(supported_types())}."
        )
    width = _TYPE_WIDTH[value_type]
    regs = [int(r) & 0xFFFF for r in registers]
    if len(regs) < width:
        raise ValueError(
            f"value_type {value_type!r} needs {width} register(s); got {len(regs)}."
        )
    if hint is None and value_min is None and value_max is None:
        raise ValueError(
            "Provide a 'hint' value and/or a 'value_min'/'value_max' range so the "
            "candidate orders can be scored — detection needs a plausibility signal."
        )

    candidates: list[dict[str, Any]] = []
    for order in orders_for(value_type):
        value = decode_value(regs, value_type, order)
        in_range = _in_range(value, value_min, value_max)
        distance = abs(value - hint) if hint is not None else None
        candidates.append(
            {"order": order, "value": value, "in_range": in_range, "distance": distance}
        )

    has_range = value_min is not None or value_max is not None
    valid = [c for c in candidates if c["in_range"]]
    pool = valid if has_range else candidates
    best, confidence = _choose(pool, hint, has_range=has_range)
    note = _explain(best, confidence, len(valid), value_type)
    # Sort the reported candidates best-first for readability (hint distance, then
    # in-range first) without mutating the scoring above.
    candidates.sort(
        key=lambda c: (not c["in_range"], c["distance"] if c["distance"] is not None else 0.0)
    )
    return {
        "value_type": value_type,
        "candidates": candidates,
        "best": best,
        "confidence": confidence,
        "note": note,
    }


def _choose(
    pool: list[dict[str, Any]], hint: float | None, *, has_range: bool
) -> tuple[dict[str, Any] | None, str]:
    """Pick the best candidate from ``pool`` and rate the confidence."""
    if not pool:
        return None, "none"
    if hint is not None:
        ranked = sorted(pool, key=lambda c: c["distance"])
        best = ranked[0]
        if len(ranked) == 1:
            return best, "high"
        runner = ranked[1]
        # Clear winner when it is far closer to the hint than the runner-up.
        margin = runner["distance"] - best["distance"]
        scale = max(abs(hint), 1.0)
        if best["distance"] <= 0.02 * scale and margin >= 0.1 * scale:
            return best, "high"
        if margin >= 0.05 * scale:
            return best, "medium"
        return best, "low"
    # Range-only: unambiguous when exactly one order lands in band.
    if has_range and len(pool) == 1:
        return pool[0], "high"
    return pool[0], "low"


def _explain(best: dict[str, Any] | None, confidence: str, n_valid: int, value_type: str) -> str:
    """Compose a short teaching note about the detection outcome."""
    if best is None:
        return (
            f"No candidate {value_type} order produced an in-range value. Widen the "
            f"range, re-check the value_type, or confirm the registers really hold a "
            f"{value_type}."
        )
    if confidence == "low":
        return (
            f"Ambiguous: {n_valid or 'several'} orders are plausible; {best['order']} is "
            f"the best guess. Provide a tighter hint/range or a second known sample."
        )
    return f"Best match: byte order {best['order']} → {best['value']} ({confidence} confidence)."
