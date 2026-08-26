"""Open-format export from the local SQLite sink — CSV / JSON / SQLite / Parquet.

The other half of the queryability layer (docs/MARKET-INSIGHTS.md R5): once
samples land in ``~/.iaiops/data.db`` (``historian_push(sink="sqlite")``), an
operator gets them into Excel / Power BI / SQL in one command. CSV uses the
stdlib, SQLite writes a fresh single-table db file, and Parquet lazy-imports
``pyarrow`` (optional extra ``iaiops[export]``) with a teaching error if missing.

**JSON is not a fourth spreadsheet format — it is the only route from a
collection run into a historian.** ``iaiops historian push --input`` consumes a
JSON list of points; the three formats above are all spreadsheet-shaped, so
until this existed the collected history that ``iaiops oee measure`` reads had
no supported path into TDengine or IoTDB. Its shape is therefore fixed by
:func:`iaiops.core.sink.base.normalize_points`, not chosen for looks — the store
column ``tag`` is emitted as ``metric`` and ``ts`` as ``timestamp`` because those
are the keys the sinks read. Found 2026-08-26 driving the demo through a lab
LAN; the bridge had to be written by hand in Python to finish the run.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from iaiops.core.sink.sqlite_local import (
    CREATE_SAMPLES_TABLE,
    DEFAULT_QUERY_LIMIT,
    SAMPLE_COLUMNS,
    SampleFilter,
    query_samples,
)

EXPORT_FORMATS = ("csv", "json", "sqlite", "parquet")
FORMAT_EXTENSIONS = {"csv": "csv", "json": "json", "sqlite": "db", "parquet": "parquet"}


def export_samples(
    fmt: str,
    out_path: Path | str,
    *,
    since: str | None = None,
    until: str | None = None,
    endpoint: str | None = None,
    tag: str | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
    db_path: Path | str | None = None,
) -> dict:
    """Export filtered samples from the local store to ``out_path`` in ``fmt``.

    Validates inputs (fail fast: unknown format / bad ISO bounds / bad limit →
    ValueError; missing local store → FileNotFoundError) and returns
    ``{format, path, rows}``.
    """
    kind = (fmt or "").strip().lower()
    if kind not in EXPORT_FORMATS:
        raise ValueError(f"Unknown export format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}.")
    out = Path(out_path).expanduser()
    if out.exists() and out.is_dir():
        raise ValueError(f"Output path {out} is a directory — pass a file path.")
    flt = SampleFilter(since=since, until=until, endpoint=endpoint, tag=tag, limit=limit)
    rows = query_samples(flt, db_path=db_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _WRITERS[kind](out, rows)
    return {"format": kind, "path": str(out), "rows": len(rows)}


def _write_csv(out: Path, rows: list[dict]) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SAMPLE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _write_sqlite(out: Path, rows: list[dict]) -> None:
    if out.exists():
        out.unlink()  # a fresh export file, not an append
    conn = sqlite3.connect(str(out))
    try:
        conn.execute(CREATE_SAMPLES_TABLE)
        conn.executemany(
            "INSERT INTO samples (ts, endpoint, protocol, tag, value, quality, unit) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [tuple(row[col] for col in SAMPLE_COLUMNS) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _write_parquet(out: Path, rows: list[dict]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValueError(
            "Parquet export needs the 'pyarrow' package. Install the export extra: "
            "pip install 'iaiops[export]'."
        ) from exc
    columns = {
        col: [str(row[col]) if col != "value" else row[col] for row in rows]
        for col in SAMPLE_COLUMNS
    }
    # ``value`` is mixed numeric/text in the store; Parquet columns are typed, so
    # keep it as text (honest, lossless) — consumers cast as needed.
    columns["value"] = ["" if v is None else str(v) for v in columns["value"]]
    pq.write_table(pa.table(columns), str(out))


def _write_json(out: Path, rows: list[dict]) -> None:
    """Write points in the shape ``historian push --input`` accepts.

    ``tag`` → ``metric`` and ``ts`` → ``timestamp`` are the whole reason this
    writer exists: ``normalize_points`` looks for those keys and DROPS a point
    that has neither, so a straight dump of the store row exports a file that
    push rejects with "No usable points to write" — a file that looks right and
    is silently useless. ``endpoint`` and ``protocol`` ride along for whoever
    reads the file; ``quality`` and ``unit`` are carried through as point tags.
    """
    points = [
        {
            "metric": row["tag"],
            "value": row["value"],
            "timestamp": row["ts"],
            "endpoint": row["endpoint"],
            "protocol": row["protocol"],
            "quality": row["quality"],
            "unit": row["unit"],
        }
        for row in rows
    ]
    out.write_text(json.dumps(points, ensure_ascii=False, indent=2), encoding="utf-8")


_WRITERS = {
    "csv": _write_csv,
    "json": _write_json,
    "sqlite": _write_sqlite,
    "parquet": _write_parquet,
}

__all__ = ["EXPORT_FORMATS", "FORMAT_EXTENSIONS", "export_samples"]
