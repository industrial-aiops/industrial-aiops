"""Fleet / multi-site rollup — one view over a whole fleet of edge SITES (READ-ONLY, pure).

`data_quality_fleet_rollup` already rolls up ENDPOINTS within one site. This is the tier above: a
central view over many **edge sites** (each its own iaiops deployment), matching the "centrally
manage a large fleet of edge sites" story. A central collector gathers a small status report per
site — via a shared historian, or by querying each site's HTTP/SSE MCP (now that transport exists) —
and these functions aggregate them.

Pure + injectable: they aggregate PROVIDED per-site reports, so they are fully unit-testable without
any live site. Nothing here connects to a device.
"""

from __future__ import annotations

from datetime import UTC, datetime

from iaiops.core.brain._shared import num, s

MAX_SITES = 10_000

# Health status tiers (worst-first) + score thresholds.
_ORDER = {"offline": 0, "critical": 1, "degraded": 2, "ok": 3, "unknown": 4}
_OK_MIN = 0.85
_DEGRADED_MIN = 0.60


def _status_from_score(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= _OK_MIN:
        return "ok"
    if score >= _DEGRADED_MIN:
        return "degraded"
    return "critical"


def _age_seconds(last_seen: str, now: datetime) -> float | None:
    text = (last_seen or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (now - dt).total_seconds()


def _site_status(site: dict, stale_after_s: float, now: datetime) -> tuple[str, float | None]:
    """Resolve one site's (status, score): explicit status > freshness(offline) > score-derived."""
    score = num(site.get("score"))
    age = _age_seconds(str(site.get("last_seen", "")), now)
    if age is not None and age > stale_after_s:
        return "offline", score
    explicit = str(site.get("status", "")).strip().lower()
    if explicit in _ORDER:
        return explicit, score
    return _status_from_score(score), score


def fleet_rollup(
    sites: list[dict],
    stale_after_s: float = 300.0,
    now: str | None = None,
) -> dict:
    """Aggregate per-site status reports into one fleet view.

    Each site report: ``{site, location?, profile?, status?, score?, issues?, last_seen?}``.
    A site is ``offline`` if ``last_seen`` is older than ``stale_after_s``. ``fleet_status`` is the
    worst site status present. Returns fleet counts, a score, and the worst sites first.
    """
    now_dt = _parse_now(now)
    rows: list[dict] = []
    for site in list(sites or [])[:MAX_SITES]:
        if not isinstance(site, dict):
            continue
        name = s(site.get("site") or site.get("name") or "", 128)
        if not name:
            continue
        status, score = _site_status(site, stale_after_s, now_dt)
        rows.append({
            "site": name,
            "location": s(site.get("location", ""), 96),
            "profile": s(site.get("profile", ""), 48),
            "status": status,
            "score": score,
            "issues": int(num(site.get("issues")) or 0),
        })

    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    scored = [r["score"] for r in rows if r["score"] is not None]
    fleet_score = round(sum(scored) / len(scored), 4) if scored else None
    # Worst status present drives the fleet verdict (offline/critical worst).
    fleet_status = (
        min((r["status"] for r in rows), key=lambda st: _ORDER.get(st, 9)) if rows else "unknown"
    )
    worst = sorted(
        rows,
        key=lambda r: (_ORDER.get(r["status"], 9), r["score"] if r["score"] is not None else 1.0),
    )
    return {
        "site_count": len(rows),
        "fleet_status": fleet_status,
        "fleet_score": fleet_score,
        "by_status": by_status,
        "worst_sites": worst[:20],
        "sites": rows,
    }


def fleet_incident_rollup(sites: list[dict]) -> dict:
    """Aggregate active RCA incidents across sites → fleet-wide top causes + affected sites.

    Each site report may carry ``incidents: [{cause, confidence?}]``. Returns total incidents, the
    sites with active incidents, and the most common causes across the fleet.
    """
    causes: dict[str, int] = {}
    affected: list[dict] = []
    total = 0
    for site in list(sites or [])[:MAX_SITES]:
        if not isinstance(site, dict):
            continue
        name = s(site.get("site") or site.get("name") or "", 128)
        incidents = [i for i in (site.get("incidents") or []) if isinstance(i, dict)]
        if not name or not incidents:
            continue
        total += len(incidents)
        affected.append({"site": name, "incident_count": len(incidents)})
        for inc in incidents:
            cause = s(inc.get("cause") or inc.get("primary_cause") or "unknown", 96)
            causes[cause] = causes.get(cause, 0) + 1
    top_causes = [
        {"cause": c, "count": n}
        for c, n in sorted(causes.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return {
        "total_incidents": total,
        "sites_with_incidents": len(affected),
        "affected_sites": sorted(affected, key=lambda a: a["incident_count"], reverse=True)[:50],
        "top_causes": top_causes[:20],
    }


def _parse_now(now: str | None) -> datetime:
    if now:
        try:
            dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(tz=UTC)


__all__ = ["fleet_rollup", "fleet_incident_rollup", "MAX_SITES"]
