"""Historian evidence for the downtime RCA copilot (A7, READ-ONLY, optional).

When a site declares a ``historian:`` block in ``config.yaml`` (see
:class:`iaiops.core.runtime.config.HistorianConfig`), this module pulls the
PRE-INCIDENT window (default 2 h before ``window.start``) from the configured
reader (:mod:`iaiops.core.sink.reader`) and shapes it as tag-trend evidence for
``downtime_rca`` — one more evidence class next to alarms / live samples /
dataflow, cited with its source (``historian:<name>``), window, and sample
count.

Strictly ADDITIVE: without the config block ``gather_pre_incident`` returns
``None`` and the copilot's behaviour is byte-identical to before. Historian
failures degrade to an honest ``{error}`` bundle (still additive context — the
copilot scores nothing from it) rather than breaking the RCA.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.brain.diagnostics import _parse_ts
from iaiops.core.runtime.config import AppConfig, load_config_env
from iaiops.core.sink.reader import get_reader
from iaiops.core.sink.sqlite_local import SampleFilter

# How far before the incident onset the historical window reaches.
PRE_INCIDENT_WINDOW_S = 7_200  # 2 h
MAX_HISTORY_TAGS = 20
MAX_SAMPLES_PER_TAG = 500
# One bounded pull for the whole window (grouped per tag afterwards).
MAX_WINDOW_ROWS = MAX_HISTORY_TAGS * MAX_SAMPLES_PER_TAG


def gather_pre_incident(
    window: dict[str, Any],
    refs: list[str] | None = None,
    config: AppConfig | None = None,
    lookback_s: int = PRE_INCIDENT_WINDOW_S,
) -> dict | None:
    """[READ] Pull the pre-incident window from the configured historian.

    Returns ``None`` when no ``historian:`` block is configured (or the window
    has no parseable ``start``) — the caller then passes nothing to the copilot
    and behaviour is unchanged. Otherwise returns an evidence bundle::

        {source: "historian:<reader>", window: {since, until},
         tag_count, sample_count, tags: [{ref, samples:[{value, good}]}]}

    ``refs`` (when given) restricts the pull to those tags; otherwise the whole
    window is pulled (bounded) and grouped per tag. A reader failure returns
    the bundle with an ``error`` instead of tags — honest, never fatal.
    """
    cfg = config if config is not None else load_config_env()
    hist = cfg.historian
    if hist is None:
        return None
    onset = _parse_ts((window or {}).get("start"))
    if onset is None:
        return None
    since = (onset - timedelta(seconds=max(0, int(lookback_s)))).isoformat()
    until = onset.isoformat()
    source = f"historian:{hist.reader}"
    bundle = {"source": source, "window": {"since": since, "until": until}}
    try:
        reader = get_reader(hist.reader, **hist.reader_opts())
    except Exception as exc:  # noqa: BLE001 — missing extra etc. → honest error
        return {**bundle, "tags": [], "tag_count": 0, "sample_count": 0, "error": s(str(exc), 200)}
    try:
        tags = _pull_tags(reader, since, until, refs)
    except Exception as exc:  # noqa: BLE001 — a query failure must not break RCA
        return {**bundle, "tags": [], "tag_count": 0, "sample_count": 0, "error": s(str(exc), 200)}
    finally:
        _close(reader)
    return {
        **bundle,
        "tags": tags,
        "tag_count": len(tags),
        "sample_count": sum(len(t["samples"]) for t in tags),
    }


def _pull_tags(reader: Any, since: str, until: str, refs: list[str] | None) -> list[dict]:
    """Query the window (per-ref when refs given, else grouped) into tag series."""
    if refs:
        wanted = [s(str(r), 128) for r in refs if r][:MAX_HISTORY_TAGS]
        out: list[dict] = []
        for ref in wanted:
            rows = reader.query(
                SampleFilter(
                    since=since,
                    until=until,
                    tag=ref,
                    limit=MAX_SAMPLES_PER_TAG,
                )
            )
            if rows:
                out.append(_series(ref, rows))
        return out
    rows = reader.query(SampleFilter(since=since, until=until, limit=MAX_WINDOW_ROWS))
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        tag = s(str(row.get("tag", "")), 128)
        if not tag:
            continue
        bucket = grouped.setdefault(tag, [])
        if len(bucket) < MAX_SAMPLES_PER_TAG:
            bucket.append(row)
    selected = sorted(grouped)[:MAX_HISTORY_TAGS]
    return [
        _series(tag, rows)
        for tag, rows in _topped_up(reader, since, until, selected, grouped, len(rows))
    ]


def _topped_up(
    reader: Any,
    since: str,
    until: str,
    selected: list[str],
    grouped: dict[str, list[dict]],
    fetched: int,
) -> list[tuple[str, list[dict]]]:
    """Re-query the selected tags when the window query was cut short.

    **Why this exists.** The grouping query is one bounded read across every tag
    (``limit=MAX_WINDOW_ROWS``), and every reader returns rows OLDEST FIRST. On a
    historian with more tags than that budget divided by
    ``MAX_SAMPLES_PER_TAG``, the cap lands long before the window ends, so each
    tag keeps only its earliest handful of samples — 40 tags against a 100-row
    budget gives 3 samples each, all from the start of the window. For a
    *pre-incident* window that discards exactly the part an investigation needs:
    the minutes just before onset.

    Measured on IoTDB and on the local SQLite store alike (2026-08-02), so this
    is not one dialect's quirk — it is what a shared row budget does to a
    per-tag question. Nothing reported it either: ``sample_count`` counted the
    diluted rows as though the window were complete.

    The re-query is skipped entirely when the first read was NOT truncated
    (``fetched < MAX_WINDOW_ROWS``), which is the common case — the whole window
    fit, so nothing is missing. Otherwise it costs at most
    ``MAX_HISTORY_TAGS`` bounded single-tag reads, the same ones the ``refs``
    branch above already makes.
    """
    if fetched < MAX_WINDOW_ROWS:
        return [(tag, grouped[tag]) for tag in selected]
    out: list[tuple[str, list[dict]]] = []
    for tag in selected:
        rows = grouped[tag]
        if len(rows) < MAX_SAMPLES_PER_TAG:
            rows = (
                reader.query(
                    SampleFilter(since=since, until=until, tag=tag, limit=MAX_SAMPLES_PER_TAG)
                )
                or rows
            )
        out.append((tag, rows))
    return out


def _series(ref: str, rows: list[dict]) -> dict:
    """Shape historian rows as the {ref, samples:[{value, good}]} tag series."""
    samples: list[dict] = []
    for row in rows[:MAX_SAMPLES_PER_TAG]:
        value = num(row.get("value"))
        samples.append({"value": value, "good": value is not None})
    return {"ref": ref, "samples": samples}


def _close(reader: Any) -> None:
    close = getattr(reader, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 — close is best-effort
            pass


__all__ = [
    "gather_pre_incident",
    "PRE_INCIDENT_WINDOW_S",
    "MAX_HISTORY_TAGS",
    "MAX_SAMPLES_PER_TAG",
]
