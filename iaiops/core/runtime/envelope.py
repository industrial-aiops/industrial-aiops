"""One unified return envelope for every bounded / list-shaped tool result.

WHY THIS EXISTS
---------------
A model reading a raw JSON tool result cannot tell a SHORT list from a
TRUNCATED one. Weak / local models (the field reality for air-gapped OT sites
running e.g. Llama 3.3 70B on-box) fail three ways on long results:

1. they miss information that IS present, or wrongly report "no data was
   returned" for a result that was merely capped;
2. they drop requested fields, or silently omit a key instead of saying the
   value was unavailable — and an OMITTED KEY IS A HALLUCINATION LICENSE,
   because the next best guess fills the hole;
3. they "beautify" raw values — severity ``800`` becomes "High", quality
   ``BAD_NOT_CONNECTED`` becomes "bad".

In IT that is a UX annoyance. In OT it is a MISDIAGNOSIS: a model that sees a
capped alarm list and concludes "this line has no active alarms" has told an
operator the plant is healthy while it is not. The fix must live in the tool
output, not in a hand-written prompt guardrail the next operator forgets to
paste.

THE CONTRACT
------------
Every bounded / list-shaped return carries these five keys, ALWAYS, whether or
not truncation occurred (see :data:`ENVELOPE_KEYS`):

``items_returned`` (int)
    How many items are actually in this response.
``items_total`` (int | None)
    How many exist upstream. Explicitly ``null`` when the call genuinely cannot
    know — e.g. a ``limit + 1`` probe that only proves "there is at least one
    more". Reporting the page size as the total would be a fabricated number.
``items_total_is_exact`` (bool)
    Whether ``items_total`` is a real count (``True``) or unknown (``False``).
    Keeps a reader from doing arithmetic on a null.
``is_truncated`` (bool)
    The unambiguous answer to "did I get everything?". Always a plain boolean,
    never a string and never a nested dict — a reader must never have to parse
    prose or walk a sub-object to learn that data is missing.
``truncation_note`` (str | None)
    Human/model-readable explanation when truncated, explicit ``null`` when not.

Names are deliberately long and self-describing: they are read by a weak model
straight out of raw JSON, with no schema to consult.

BACKWARD COMPATIBILITY
----------------------
These keys are ADDITIVE. The published tools already carry legacy truncation
keys of three different types — a string (``maintenance_log``), a per-section
dict (``alarm_flood_report``), and a bool (everywhere else) — and that very
inconsistency is the hazard. Retyping a published key would break consumers, so
the legacy keys are left exactly as they are and the envelope is added
alongside. ``is_truncated`` is the one key a reader should trust.

TWO SUPPORTING RULES
--------------------
* **Explicit nulls** — :func:`with_explicit_nulls` renders a requested-but-absent
  field as an explicit ``null`` instead of omitting the key.
* **Enum passthrough** — raw OT enum / severity / quality / state values are
  passed through VERBATIM, never translated, ranked, or prettified.
  :func:`enum_passthrough_violations` makes that assertable in tests.

Every helper here is pure: it returns NEW containers and never mutates its
arguments.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

# --- envelope key names (import these; never hand-spell the strings) -------

ITEMS_RETURNED: Final = "items_returned"
ITEMS_TOTAL: Final = "items_total"
ITEMS_TOTAL_IS_EXACT: Final = "items_total_is_exact"
IS_TRUNCATED: Final = "is_truncated"
TRUNCATION_NOTE: Final = "truncation_note"

#: The full contract. A bounded return carries ALL of these, always.
ENVELOPE_KEYS: Final[tuple[str, ...]] = (
    ITEMS_RETURNED,
    ITEMS_TOTAL,
    ITEMS_TOTAL_IS_EXACT,
    IS_TRUNCATED,
    TRUNCATION_NOTE,
)

#: Default note when the caller does not supply a more specific one.
_EXACT_NOTE: Final = (
    "TRUNCATED: {returned} of {total} items returned — {missing} were NOT included. "
    "Do not conclude anything from their absence; narrow the query or raise the limit."
)
_PROBE_NOTE: Final = (
    "TRUNCATED: {returned} items returned and MORE EXIST upstream (exact total unknown). "
    "Do not conclude anything from their absence; narrow the query or raise the limit."
)

#: Field names whose values are raw OT enums / codes and must never be rewritten.
#: Used by :func:`enum_passthrough_violations` as a sensible default set.
OT_PASSTHROUGH_FIELDS: Final[tuple[str, ...]] = (
    "severity",
    "priority",
    "criticality",
    "quality",
    "status",
    "state",
    "impact",
    "condition",
    "alarm_state",
    "event_type",
    "error_code",
    "fault_code",
)


def envelope_fields(
    *,
    returned: int,
    total: int | None = None,
    more_available: bool | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Build the five envelope keys as a new dict — merge into any tool return.

    Exactly ONE source of truth must be supplied:

    * ``total`` — the exact upstream count is known. Truncation is then simply
      ``returned < total``, which makes the boundary ``returned == total``
      correctly NOT truncated.
    * ``more_available`` — the exact total is unknown (the classic ``limit + 1``
      probe, which proves only that at least one more row exists). ``items_total``
      is then an explicit ``null`` and ``items_total_is_exact`` is ``False``.

    Args:
        returned: Number of items in this response. Must be >= 0.
        total: Exact upstream total, if known. Must be >= ``returned``.
        more_available: Whether more items exist upstream, when the total is not
            knowable.
        note: Optional caller-supplied ``truncation_note``. Ignored (forced to
            ``None``) when nothing was truncated, so the note can never contradict
            ``is_truncated``.

    Returns:
        A new dict with exactly :data:`ENVELOPE_KEYS`.

    Raises:
        ValueError: If neither or both sources of truth are given, or the counts
            are impossible (negative, or ``total < returned``).
    """
    if (total is None) == (more_available is None):
        raise ValueError(
            "envelope_fields requires exactly one of total= (exact count known) "
            "or more_available= (limit+1 probe, exact count unknown)."
        )
    if returned < 0:
        raise ValueError(f"returned must be >= 0 (got {returned}).")

    if total is not None:
        if total < returned:
            raise ValueError(f"total ({total}) cannot be smaller than returned ({returned}).")
        truncated = returned < total
        default_note = _EXACT_NOTE.format(returned=returned, total=total, missing=total - returned)
    else:
        truncated = bool(more_available)
        default_note = _PROBE_NOTE.format(returned=returned)

    return {
        ITEMS_RETURNED: int(returned),
        ITEMS_TOTAL: None if total is None else int(total),
        ITEMS_TOTAL_IS_EXACT: total is not None,
        IS_TRUNCATED: truncated,
        TRUNCATION_NOTE: (note or default_note) if truncated else None,
    }


def bounded(
    items: Sequence[Any],
    cap: int,
    *,
    items_key: str = "items",
    note: str | None = None,
) -> dict[str, Any]:
    """Cap a fully-materialized sequence and return it inside a full envelope.

    Use when the complete collection is already in memory, so the exact total is
    known. When only a page was fetched, use :func:`envelope_fields` with
    ``more_available`` instead of inventing a total.

    Args:
        items: The complete collection (never mutated; a new list is returned).
        cap: Maximum number of items to include. Must be >= 0.
        items_key: Name of the list key in the returned dict.
        note: Optional ``truncation_note`` override.

    Returns:
        A new dict: ``{items_key: [...], **envelope_fields(...)}``.

    Raises:
        ValueError: If ``cap`` is negative.
    """
    if cap < 0:
        raise ValueError(f"cap must be >= 0 (got {cap}).")
    total = len(items)
    kept = list(items[:cap])
    return {items_key: kept, **envelope_fields(returned=len(kept), total=total, note=note)}


def with_explicit_nulls(
    data: Mapping[str, Any],
    fields: Iterable[str],
) -> dict[str, Any]:
    """Return a copy of ``data`` where every name in ``fields`` is present.

    A field that was requested but is unavailable comes back as an explicit
    ``null`` rather than a missing key. An omitted key invites a reader to infer
    the value; an explicit ``null`` says "not available" out loud.

    Existing values are never overwritten — including falsy ones such as ``0``,
    ``""`` and ``False``, which are real OT readings, not absences.

    Args:
        data: Source mapping (never mutated).
        fields: Field names that must exist in the result.

    Returns:
        A new dict containing everything in ``data`` plus any missing ``fields``
        set to ``None``.
    """
    out = dict(data)
    for field in fields:
        if field not in out:
            out[field] = None
    return out


def enum_passthrough_violations(
    source: Sequence[Mapping[str, Any]],
    returned: Sequence[Mapping[str, Any]],
    fields: Iterable[str] = OT_PASSTHROUGH_FIELDS,
) -> list[dict[str, Any]]:
    """Report every field whose raw OT value was altered or dropped in transit.

    Raw enum / severity / quality / state values MUST be passed through verbatim.
    Translating OPC-UA severity ``800`` to "High", or normalizing
    ``BAD_NOT_CONNECTED`` to "bad", destroys the exact value an operator matches
    against the vendor's own documentation — and invents a ranking iaiops has no
    authority to assert. Dropping the field entirely is equally dangerous.

    Comparison is by identity of value AND type (``1`` is not ``True``, ``800``
    is not ``"800"``), because a stringified enum is already a rewrite.

    Args:
        source: Rows as read from the device / store.
        returned: The corresponding rows as emitted by the tool, same order.
        fields: Field names to check. Defaults to :data:`OT_PASSTHROUGH_FIELDS`.

    Returns:
        A list of ``{index, field, source_value, returned_value}`` dicts — empty
        when every checked value survived verbatim.

    Raises:
        ValueError: If the two sequences differ in length (a row was added or
            lost, which no passthrough check can meaningfully interpret).
    """
    if len(source) != len(returned):
        raise ValueError(
            f"source has {len(source)} rows but returned has {len(returned)} — "
            "enum passthrough compares rows pairwise and cannot align these."
        )
    names = tuple(fields)
    violations: list[dict[str, Any]] = []
    for index, (src_row, out_row) in enumerate(zip(source, returned, strict=True)):
        for field in names:
            if field not in src_row:
                continue
            src_value = src_row[field]
            if field not in out_row:
                violations.append(
                    {
                        "index": index,
                        "field": field,
                        "source_value": src_value,
                        "returned_value": None,
                        "reason": "field dropped",
                    }
                )
                continue
            out_value = out_row[field]
            if type(src_value) is not type(out_value) or src_value != out_value:
                violations.append(
                    {
                        "index": index,
                        "field": field,
                        "source_value": src_value,
                        "returned_value": out_value,
                        "reason": "value altered",
                    }
                )
    return violations


__all__ = [
    "ENVELOPE_KEYS",
    "IS_TRUNCATED",
    "ITEMS_RETURNED",
    "ITEMS_TOTAL",
    "ITEMS_TOTAL_IS_EXACT",
    "OT_PASSTHROUGH_FIELDS",
    "TRUNCATION_NOTE",
    "bounded",
    "enum_passthrough_violations",
    "envelope_fields",
    "with_explicit_nulls",
]
