"""Push collected OT telemetry to a historian sink (TDengine / IoTDB / local SQLite).

The orchestration the MCP tool / CLI call: normalize a list of collected points,
open the requested sink, write, and always close — returning an honest tally
(written vs skipped non-numeric). Data egress to the operator's OWN historian
(low-risk, governed), not a control-system write. The ``sqlite`` sink is the
local queryable store (``~/.iaiops/data.db``) feeding ``iaiops export`` and the
Prometheus exporter; it keeps non-numeric values too (stored as text).
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.sink.base import (
    SUPPORTED_SINKS,
    TEXT_CAPABLE_SINKS,
    SinkError,
    get_sink,
    normalize_points,
)


def historian_push(points: list[Any], sink: str, **opts: Any) -> dict:
    """[WRITE→historian] Normalize and write points to a historian sink.

    ``sink`` is ``tdengine``, ``iotdb`` or ``sqlite`` (the local queryable store);
    ``opts`` carries the connection params (host/port/user/password/database, and
    stable for TDengine). Returns a tally; non-numeric points are skipped by the
    TSDBs (numeric value column) but kept as text by the sqlite sink.
    """
    kind = (sink or "").strip().lower()
    if kind not in SUPPORTED_SINKS:
        return {"error": f"Unknown sink '{sink}'. Supported: {', '.join(SUPPORTED_SINKS)}."}
    normalized = normalize_points(points)
    if not normalized:
        return {"error": "No usable points to write (need [{ref|metric, value, ...}])."}
    numeric = [p for p in normalized if p["numeric"]]
    # SQLite keeps text values too; the TSDBs store a numeric value column only.
    writable = normalized if kind in TEXT_CAPABLE_SINKS else numeric
    adapter = get_sink(kind, **opts)
    try:
        written = int(adapter.write(writable))
    except SinkError as exc:
        return {"error": s(str(exc), 200), "sink": kind}
    except Exception as exc:  # noqa: BLE001 — any client-lib failure → a teaching tally error
        return {"error": s(f"{kind} write failed: {exc}", 200), "sink": kind}
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 — close must not mask the result
                pass
    note = (
        "Telemetry written to the local queryable SQLite store — query it with "
        "'iaiops export' or scrape it via 'iaiops metrics serve'."
        if kind in TEXT_CAPABLE_SINKS
        else "Telemetry written to the operator's national TSDB historian "
        "(信创). Data egress only — not a control-system write."
    )
    return {
        "sink": kind,
        "received": len(normalized),
        "written": written,
        "skipped_non_numeric": len(normalized) - len(writable),
        "database": s(opts.get("database", ""), 64),
        "note": note,
    }


__all__ = ["historian_push"]
