"""Match scanned device identities against a mounted advisory library.

`iaiops scan` already reads vendor, model, firmware and serial off the devices it
finds, and then does nothing with them. The obvious next step — "which of these
have published advisories against them" — is also the easiest place in this
product to say something false, so the shape here is copied from the
fault-mechanism library rather than from a vulnerability scanner.

**It reports that a device falls inside an advisory's stated range. Nothing
more.** Not "vulnerable", not "exploitable", not a severity score. Whether a
published issue is reachable on a particular machine depends on configuration,
network position and compensating controls that this tool cannot see, and in OT
the difference matters: an advisory against a protocol stack that is only
reachable from a network nobody can route to is not a finding, and treating it
as one is how a report full of red text gets switched off by the site.

**No database ships with this.** A bundled CVE feed is a maintenance commitment
this repo has not made, and a stale one that looks current is worse than none —
so the library is mounted from a file the site controls, which also makes it work
air-gapped. Every match cites the advisory id and the source it came from.

Four verdicts, and the middle one is the point:

``in_affected_range``    identity matches and the firmware falls in the range
``version_unknown``      the model matches but no firmware was read — the honest
                         middle state, neither a hit nor a pass
``version_unparsed``     a firmware string this cannot compare; refuses rather
                         than guessing an ordering
``not_affected``         identity matches and the version is outside the range

A device no advisory mentions is absent from the findings, not reported as
clean: the library is whatever the site mounted, and "nothing known" is not
"nothing there".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.envelope import envelope_fields

MAX_DEVICES = 5_000
MAX_ADVISORIES = 5_000
MAX_FINDINGS = 500

IN_RANGE = "in_affected_range"
VERSION_UNKNOWN = "version_unknown"
VERSION_UNPARSED = "version_unparsed"
NOT_AFFECTED = "not_affected"

_NORM = re.compile(r"[^a-z0-9]+")
_VERSION_PART = re.compile(r"\d+")

ADVISORY_NOTE = (
    "Falling inside a published advisory's range is not the same as being exploitable: "
    "reachability, configuration and compensating controls decide that, and none of them "
    "are visible from a read-only scan. These are leads to assess, not findings to fix."
)


def _norm(text: Any) -> str:
    return _NORM.sub("", s(text, 96).lower())


def parse_version(raw: Any) -> tuple[int, ...] | None:
    """A comparable version tuple, or None when the string cannot be ordered.

    Deliberately narrow: dotted decimal only. Vendor firmware strings are a zoo
    (``V2.9.2``, ``2.9.2-rc1``, ``Rev C``) and inventing an ordering for the ones
    that are not obviously numeric would produce a confident wrong comparison.
    """
    text = s(raw, 64).strip()
    if not text:
        return None
    core = text.lstrip("vVrR").split("-")[0].split("+")[0].split(" ")[0]
    parts = core.split(".")
    if not parts or not all(_VERSION_PART.fullmatch(p) for p in parts if p != ""):
        return None
    nums = tuple(int(p) for p in parts if p != "")
    return nums or None


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)), b + (0,) * (width - len(b))


def _in_range(version: tuple[int, ...], advisory: dict) -> bool | None:
    """True/False if decidable, None when the advisory states no usable range."""
    listed = advisory.get("affected_versions")
    if isinstance(listed, list) and listed:
        wanted = {parse_version(v) for v in listed}
        return version in {w for w in wanted if w}
    below = parse_version(advisory.get("affected_below"))
    at_or_above = parse_version(advisory.get("affected_from"))
    if below is None and at_or_above is None:
        return None
    if below is not None:
        left, right = _pad(version, below)
        if left >= right:
            return False
    if at_or_above is not None:
        left, right = _pad(version, at_or_above)
        if left < right:
            return False
    return True


def _advisory_rows(advisories: Any) -> list[dict]:
    if not isinstance(advisories, list):
        raise ValueError("advisories must be a list of {id, vendor, model, ...} entries.")
    rows = []
    for raw in advisories[:MAX_ADVISORIES]:
        if not isinstance(raw, dict):
            continue
        ident = s(raw.get("id", ""), 64).strip()
        vendor = _norm(raw.get("vendor"))
        model = _norm(raw.get("model"))
        if not ident or not vendor or not model:
            raise ValueError(
                "Every advisory needs id, vendor and model — an entry without them "
                f"cannot be matched to a device or cited back: {raw!r}"[:300]
            )
        if not s(raw.get("source", ""), 200).strip():
            raise ValueError(
                f"Advisory {ident!r} has no source. An advisory with no provenance is "
                "indistinguishable from a guess a year later."
            )
        rows.append(raw)
    return rows


def match_devices(devices: list[dict], advisories: list[dict]) -> dict[str, Any]:
    """[PURE] Which scanned devices fall inside a mounted advisory's stated range."""
    if not isinstance(devices, list):
        raise ValueError("devices must be a list of {ip?, vendor, model, firmware?} rows.")
    entries = _advisory_rows(advisories)

    findings: list[dict] = []
    matched_devices: set[str] = set()
    for device in devices[:MAX_DEVICES]:
        if not isinstance(device, dict):
            continue
        vendor, model = _norm(device.get("vendor")), _norm(device.get("model"))
        if not vendor or not model:
            continue
        firmware = device.get("firmware")
        version = parse_version(firmware)
        for advisory in entries:
            if _norm(advisory.get("vendor")) != vendor or _norm(advisory.get("model")) != model:
                continue
            if version is None:
                status = VERSION_UNPARSED if s(firmware, 64).strip() else VERSION_UNKNOWN
                detail = (
                    f"firmware {s(firmware, 64)!r} is not a dotted version this can order — "
                    "not compared rather than guessed"
                    if status == VERSION_UNPARSED
                    else "the scan read no firmware for this device, so the range was not applied"
                )
            else:
                verdict = _in_range(version, advisory)
                if verdict is None:
                    status, detail = VERSION_UNKNOWN, "the advisory states no version range"
                elif verdict:
                    status = IN_RANGE
                    detail = f"firmware {s(firmware, 64)} falls inside the stated range"
                else:
                    status = NOT_AFFECTED
                    detail = f"firmware {s(firmware, 64)} is outside the stated range"
            findings.append(
                {
                    "ip": s(device.get("ip", ""), 64),
                    "vendor": s(device.get("vendor", ""), 96),
                    "model": s(device.get("model", ""), 96),
                    "firmware": s(firmware, 64),
                    "advisory_id": s(advisory.get("id", ""), 64),
                    "title": s(advisory.get("title", ""), 200),
                    "source": s(advisory.get("source", ""), 200),
                    "status": status,
                    "detail": detail,
                }
            )
            matched_devices.add(s(device.get("ip", ""), 64) or f"{vendor}/{model}")

    order = {IN_RANGE: 0, VERSION_UNPARSED: 1, VERSION_UNKNOWN: 2, NOT_AFFECTED: 3}
    findings.sort(key=lambda f: (order.get(f["status"], 9), f["advisory_id"], f["ip"]))
    counts = {k: sum(1 for f in findings if f["status"] == k) for k in order}
    return {
        "devices_checked": sum(1 for d in devices[:MAX_DEVICES] if isinstance(d, dict)),
        "advisories_mounted": len(entries),
        "devices_with_findings": len(matched_devices),
        "summary": counts,
        "findings": findings[:MAX_FINDINGS],
        # The standard envelope rather than a bare `truncated` flag — a gate in
        # tests/test_envelope_gate.py enforces that, so a caller can tell "50
        # findings" from "the first 50 of 900" the same way in every tool.
        **envelope_fields(returned=min(len(findings), MAX_FINDINGS), total=len(findings)),
        "advisory_note": ADVISORY_NOTE,
        "note": (
            "Devices no mounted advisory mentions are absent from this list — that is "
            "'nothing known', not 'nothing there'. The library is whatever this site "
            "mounted, and its coverage is the site's to know."
        ),
    }


def load_advisories(path: Path | str) -> list[dict]:
    """Read a mounted advisory library (YAML or JSON) and validate every entry."""
    import json

    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ValueError(f"No advisory library at {resolved}.")
    text = resolved.read_text("utf-8")
    if resolved.suffix.lower() in (".yaml", ".yml"):
        import yaml

        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    entries = payload.get("advisories") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError(
            f"{resolved} must hold a list of advisories, or an object with an 'advisories' list."
        )
    _advisory_rows(entries)  # all-or-nothing: one bad entry refuses the file
    return entries


__all__ = [
    "ADVISORY_NOTE",
    "IN_RANGE",
    "NOT_AFFECTED",
    "VERSION_UNKNOWN",
    "VERSION_UNPARSED",
    "load_advisories",
    "match_devices",
    "parse_version",
]
