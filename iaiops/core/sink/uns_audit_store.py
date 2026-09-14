"""The last namespace audit per broker endpoint — what lets onboard fork B1/B2.

``iaiops onboard status`` contacts nothing, so it cannot find out for itself
whether a site's UNS namespace is governed. ``uns-live-audit`` leaves its verdict
here, from both front ends, and onboard reads it back — the same arrangement as a
scan leaving its result in the scan store for the devices journey.

A stored verdict is evidence about ONE capture, so the record keeps what that
capture could and could not establish, and the store refuses what establishes
nothing:

* **Refused at save:** a result carrying an error; no verdict; zero topics; zero
  messages observed. ``uns_topic_audit`` answers an empty topic list with an error
  and no verdict, and storing it would read "zero findings" as a clean namespace.
* **Recorded, so a reader can discount it:** the topic filter that was captured
  and the broker it came from (an audit of a narrow filter, or of a different
  broker, does not describe this endpoint now); whether a naming standard was
  declared (without ``--root`` and ``--min-segments`` two of the six checks cannot
  fire, so "clean" is weak); and whether the capture hit its message cap (a
  truncated capture saw part of the namespace, not all of it).
* **Validated at load exactly as at save.** A hand-edited or corrupted file that
  the save side would have refused comes back as a file problem, never as a
  verdict — and so does a date in the future or no date at all.

Files are named from a hash of the FULL endpoint name. Truncating or sanitising a
name into a file name let two endpoints share one file: a long name borrowed
another endpoint's verdict, and two non-ASCII names overwrote each other.

Stored under ``IAIOPS_HOME`` (``ops_path``), which the test isolation moves.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from iaiops.core.governance.paths import ops_path

SUBDIR = "uns_audits"
_FORMAT_VERSION = 3
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
#: Names at or above this length may already have been truncated by the live
#: capture (``live._capture_topics`` bounds ``capture.endpoint`` to 64). A caller
#: that does not pass the endpoint explicitly gets a refusal for such a name
#: rather than a verdict filed under a name that is not quite its own.
_CAPTURE_NAME_BOUND = 64
#: Clock skew tolerated before a stored date counts as "in the future".
_FUTURE_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class UnsAuditRecord:
    """One stored verdict and what its capture could establish — or why the stored
    file could not be read."""

    endpoint: str
    verdict: str = ""
    sprawl_findings: int = 0
    topic_count: int = 0
    observed_messages: int = 0
    audited_at: str = ""
    #: The topic filter the capture subscribed to.
    topic_filter: str = ""
    #: ``host:port`` of the broker that was audited.
    broker: str = ""
    allowed_roots: tuple[str, ...] = ()
    min_segments: int = 0
    max_msgs: int = 0
    #: The capture stopped at its message cap, so it saw part of the namespace.
    capture_capped: bool = False
    #: How long the capture listened. A topic that publishes less often than this
    #: was never seen, so it could not be judged.
    duration_s: int = 0
    #: Set only when the stored FILE could not be read or failed validation. About
    #: the file, never about the namespace.
    error: str = ""

    @property
    def naming_standard(self) -> bool:
        """Whether the audit ran against a declared standard: roots AND a depth."""
        return bool(self.allowed_roots) and self.min_segments > 0


def _count(value: Any, *, positive: bool) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < 0 or (positive and value == 0):
        return None
    return value


def _root(base_dir: Any) -> Path:
    return Path(base_dir) if base_dir else ops_path(SUBDIR)


#: ``uns_topic_audit``'s own rule: the verdict is a function of the finding count.
def verdict_for(findings: int) -> str:
    return "clean" if findings == 0 else ("minor" if findings <= 5 else "sprawling")


def audit_file(endpoint: str, base_dir: Any = None) -> Path:
    """Where ``endpoint``'s audit lives. Unique per full name, not per sanitised name."""
    name = str(endpoint)
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    safe = _UNSAFE.sub("_", name.strip())[:48].strip("_") or "endpoint"
    return _root(base_dir) / f"{safe}-{digest}.json"


def save_uns_audit(
    result: Any,
    *,
    endpoint: str | None = None,
    broker: str = "",
    allowed_roots: Any = None,
    min_segments: int = 0,
    max_msgs: int = 0,
    duration_s: int = 0,
    base_dir: Any = None,
    now: datetime | None = None,
) -> Path | None:
    """Store a live audit's verdict, or refuse; returns the path it was stored at.

    ``endpoint`` should be the configured endpoint name. When it is omitted the
    capture's own ``endpoint`` is used — and refused if it is long enough that the
    capture may have truncated it.
    """
    if not isinstance(result, dict) or result.get("error"):
        return None
    capture = result.get("capture")
    capture = capture if isinstance(capture, dict) else {}
    if endpoint is None:
        name = str(capture.get("endpoint") or "").strip()
        if len(name) >= _CAPTURE_NAME_BOUND:
            return None
    else:
        name = str(endpoint).strip()
    verdict = str(result.get("verdict") or "").strip()
    topics = _count(result.get("topic_count"), positive=True)
    observed = _count(capture.get("observed_messages"), positive=True)
    findings = _count(result.get("sprawl_findings"), positive=False)
    if not name or topics is None or observed is None or findings is None:
        return None
    if verdict != verdict_for(findings):
        return None

    roots = [str(r) for r in (allowed_roots or ()) if str(r).strip()]
    depth = _count(min_segments, positive=False) or 0
    cap = _count(max_msgs, positive=False) or 0
    path = audit_file(name, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": _FORMAT_VERSION,
        "endpoint": name,
        "verdict": verdict,
        "sprawl_findings": findings,
        "topic_count": topics,
        "observed_messages": observed,
        "audited_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "topic_filter": str(capture.get("topic") or ""),
        "broker": str(broker or ""),
        "allowed_roots": roots,
        "min_segments": depth,
        "max_msgs": cap,
        # No recorded cap is not evidence the capture was whole.
        "capture_capped": bool(not cap or observed >= cap),
        "duration_s": _count(duration_s, positive=False) or 0,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)
    return path


def broker_id(target: Any) -> str:
    """``host:port`` exactly as the endpoint's config gives it.

    The same expression at save time and at comparison time, so an endpoint whose
    broker has not changed always matches its own audit — and one repointed at a
    different broker never does.
    """
    return f"{str(getattr(target, 'host', '') or '')}:{getattr(target, 'port', 0) or 0}"


def _invalid(endpoint: str, why: str) -> UnsAuditRecord:
    return UnsAuditRecord(endpoint=endpoint, error=why)


def load_uns_audit(
    endpoint: str, base_dir: Any = None, now: datetime | None = None
) -> UnsAuditRecord | None:
    """The stored verdict for ``endpoint``; None when none was ever stored."""
    path = audit_file(endpoint, base_dir)
    try:
        if not path.exists():
            return None
        doc = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        return _invalid(endpoint, f"{type(exc).__name__}: {exc}")
    if not isinstance(doc, dict):
        return _invalid(endpoint, "the stored file is not an audit record")
    if doc.get("version") != _FORMAT_VERSION:
        return _invalid(
            endpoint,
            f"the stored audit is format {doc.get('version')!r}, not {_FORMAT_VERSION} — re-audit",
        )
    if str(doc.get("endpoint", "")) != str(endpoint):
        return None

    verdict = doc.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        return _invalid(endpoint, "the stored audit carries no verdict")
    topics = _count(doc.get("topic_count"), positive=True)
    if topics is None:
        return _invalid(endpoint, "the stored audit has no positive topic_count")
    findings = _count(doc.get("sprawl_findings"), positive=False)
    if findings is None:
        return _invalid(endpoint, "the stored audit's sprawl_findings is not a count")
    if verdict.strip() != verdict_for(findings):
        return _invalid(
            endpoint, f"the stored verdict {verdict!r} does not match its {findings} finding(s)"
        )
    observed = _count(doc.get("observed_messages"), positive=True)
    if observed is None:
        return _invalid(endpoint, "the stored audit observed no messages")
    try:
        stamp = datetime.fromisoformat(str(doc.get("audited_at")).replace("Z", "+00:00"))
    except ValueError:
        return _invalid(endpoint, "the stored audit has no valid date")
    if stamp.tzinfo is None:
        return _invalid(endpoint, "the stored audit's date has no timezone")
    if stamp > (now or datetime.now(UTC)) + _FUTURE_SKEW:
        return _invalid(endpoint, "the stored audit is dated in the future")
    roots = doc.get("allowed_roots", [])
    if not isinstance(roots, list) or not all(isinstance(r, str) and r.strip() for r in roots):
        return _invalid(endpoint, "the stored audit's allowed_roots is not a list of names")
    depth = _count(doc.get("min_segments", 0), positive=False)
    cap = _count(doc.get("max_msgs", 0), positive=False)
    duration = _count(doc.get("duration_s", 0), positive=False)
    capped = doc.get("capture_capped", True)
    if depth is None or cap is None or duration is None or not isinstance(capped, bool):
        return _invalid(endpoint, "the stored audit's capture limits are malformed")
    return UnsAuditRecord(
        endpoint=endpoint,
        verdict=verdict.strip(),
        sprawl_findings=findings,
        topic_count=topics,
        observed_messages=observed,
        audited_at=stamp.isoformat(timespec="seconds"),
        topic_filter=str(doc.get("topic_filter") or ""),
        broker=str(doc.get("broker") or ""),
        allowed_roots=tuple(roots),
        min_segments=depth,
        max_msgs=cap,
        # Recomputed, not trusted: a file saying "not capped" beside a count that
        # reached the cap, or beside no cap at all, cannot vouch the capture was whole.
        capture_capped=bool(capped or not cap or observed >= cap),
        duration_s=duration,
    )


__all__ = [
    "SUBDIR",
    "UnsAuditRecord",
    "audit_file",
    "broker_id",
    "load_uns_audit",
    "save_uns_audit",
    "verdict_for",
]
