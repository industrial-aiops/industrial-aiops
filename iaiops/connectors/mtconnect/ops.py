"""MTConnect operations (royalty-free standard for ALL CNC machine tools).

MTConnect is a **read-only by specification** standard: a machine-tool *agent*
exposes a REST interface returning XML — ``/probe`` (the device model), ``/current``
(latest values), ``/sample`` (a bounded stream of observations), and ``/assets``.
This module speaks plain HTTP (``requests``) + ``xml.etree`` (no heavy SDK) and is
vendor-neutral across Fanuc / Siemens / Haas / Mazak / Okuma controllers that
ship an MTConnect agent.

The HTTP fetch is a module-level function (``_http_get``) so tests can inject a
static XML fixture without a live agent. All agent-returned text is sanitized.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: N817 — conventional ET alias
from typing import Any

from iaiops.core.brain._shared import num, s

MAX_OBSERVATIONS = 500
DEFAULT_SAMPLE_COUNT = 100
MAX_SAMPLE_COUNT = 500
_HTTP_TIMEOUT_S = 10

# DataItem ids/types whose latest value an OEE snapshot cares about.
_OEE_AVAILABILITY = "AVAILABILITY"
_OEE_EXECUTION = "EXECUTION"
_OEE_MODE = "CONTROLLERMODE"
_OEE_PROGRAM = "PROGRAM"


def _http_get(url: str, timeout: int = _HTTP_TIMEOUT_S) -> str:
    """Fetch ``url`` and return the response body as text. Monkeypatched in tests."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover — exercised only without requests
        from iaiops.core.runtime.connection import OTConnectionError

        raise OTConnectionError(
            "The 'requests' package is not installed. Install the MTConnect "
            "connector: 'pip install iaiops[mtconnect]'."
        ) from exc

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _agent_base(target: Any) -> str:
    """Resolve the MTConnect agent base URL from the endpoint config."""
    base = (getattr(target, "agent_url", "") or "").rstrip("/")
    if not base and getattr(target, "host", ""):
        port = target.port or 5000
        base = f"http://{target.host}:{port}"
    if not base:
        raise ValueError(
            f"MTConnect endpoint '{target.name}' has no agent_url. Add "
            f"'agent_url: http://host:5000' (or host/port) to its config entry."
        )
    return base


def _strip(tag: str) -> str:
    """Drop the XML namespace from a tag, leaving the local name."""
    return tag.rsplit("}", 1)[-1]


def _fetch_xml(target: Any, path: str, query: str = "") -> ET.Element:
    """GET ``{agent}/{path}`` and parse the XML root (namespaces left intact)."""
    base = _agent_base(target)
    url = f"{base}/{path}"
    if query:
        url = f"{url}?{query}"
    body = _http_get(url)
    # Defense-in-depth against XXE / billion-laughs from a compromised agent:
    # MTConnect documents never carry a DTD or entity declarations, so reject any
    # before parsing. stdlib ElementTree does not resolve external entities, and
    # with DTD/entities barred there is no expansion vector.
    lowered = body[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError(
            f"MTConnect agent at {url} returned XML with a DTD/entity declaration; "
            f"refused (XXE/entity-expansion defense). MTConnect XML carries neither."
        )
    try:
        return ET.fromstring(body)  # nosec B314 — DTD/entities barred above; ET resolves no externals
    except ET.ParseError as exc:
        raise ValueError(f"MTConnect agent at {url} returned unparseable XML: {exc}") from exc


def mtconnect_probe(target: Any) -> dict:
    """[READ] The device model: devices → components → data items (the 'schema')."""
    root = _fetch_xml(target, "probe")
    devices: list[dict] = []
    for dev in root.iter():
        if _strip(dev.tag) != "Device":
            continue
        components: list[dict] = []
        for comp in dev.iter():
            if comp is dev:
                continue
            # A component is any element with a direct <DataItems> container; only
            # its DIRECT DataItem children belong to it (avoids nested double-count).
            container = next((c for c in comp if _strip(c.tag) == "DataItems"), None)
            if container is None:
                continue
            items = [_dataitem(di) for di in container if _strip(di.tag) == "DataItem"]
            if items:
                components.append(
                    {
                        "component": s(_strip(comp.tag), 48),
                        "id": s(comp.get("id", ""), 64),
                        "name": s(comp.get("name", ""), 64),
                        "data_items": items[:MAX_OBSERVATIONS],
                    }
                )
        devices.append(
            {
                "name": s(dev.get("name", ""), 64),
                "uuid": s(dev.get("uuid", ""), 96),
                "component_count": len(components),
                "components": components,
            }
        )
    return {"endpoint": s(target.name, 64), "device_count": len(devices), "devices": devices}


def _dataitem(di: ET.Element) -> dict:
    """Compact, sanitized descriptor for one MTConnect DataItem definition."""
    return {
        "id": s(di.get("id", ""), 64),
        "type": s(di.get("type", ""), 48),
        "category": s(di.get("category", ""), 24),
        "name": s(di.get("name", ""), 64),
        "units": s(di.get("units", ""), 24),
    }


def _observations(root: ET.Element) -> list[dict]:
    """Walk a Streams document; collect every element carrying a dataItemId."""
    out: list[dict] = []
    for el in root.iter():
        if "dataItemId" not in el.attrib:
            continue
        out.append(
            {
                "data_item_id": s(el.get("dataItemId", ""), 64),
                "type": s(_strip(el.tag), 48),
                "name": s(el.get("name", ""), 64),
                "timestamp": s(el.get("timestamp", ""), 40),
                "sequence": s(el.get("sequence", ""), 24),
                "value": s((el.text or "").strip(), 256),
            }
        )
        if len(out) >= MAX_OBSERVATIONS:
            break
    return out


def mtconnect_current(target: Any) -> dict:
    """[READ] Latest value of every data item (a snapshot of the machine now)."""
    root = _fetch_xml(target, "current")
    obs = _observations(root)
    return {"endpoint": s(target.name, 64), "observation_count": len(obs), "observations": obs}


def mtconnect_sample(target: Any, count: int = DEFAULT_SAMPLE_COUNT) -> dict:
    """[READ] A BOUNDED stream of recent observations (count capped server-side)."""
    count = max(1, min(int(count), MAX_SAMPLE_COUNT))
    root = _fetch_xml(target, "sample", query=f"count={count}")
    obs = _observations(root)
    return {
        "endpoint": s(target.name, 64),
        "requested_count": count,
        "observation_count": len(obs),
        "observations": obs,
    }


def mtconnect_assets(target: Any) -> dict:
    """[READ] Assets the agent knows (cutting tools, fixtures, programs)."""
    root = _fetch_xml(target, "assets")
    assets: list[dict] = []
    for el in root.iter():
        if _strip(el.tag) != "Assets":
            continue
        for asset in list(el):
            assets.append(
                {
                    "asset_type": s(_strip(asset.tag), 48),
                    "asset_id": s(asset.get("assetId", ""), 64),
                    "timestamp": s(asset.get("timestamp", ""), 40),
                }
            )
        break
    return {
        "endpoint": s(target.name, 64),
        "asset_count": len(assets),
        "assets": assets[:MAX_OBSERVATIONS],
    }


def mtconnect_oee_snapshot(target: Any) -> dict:
    """[READ] Availability / Execution / mode / program from /current (OEE inputs).

    Pulls the key data items an availability/performance calculation needs. Does
    NOT compute a single OEE percentage (that needs planned-time + ideal-cycle
    context this preview cannot know) — it surfaces the live inputs for an agent.
    """
    root = _fetch_xml(target, "current")
    obs = _observations(root)
    picks: dict[str, dict] = {}
    for o in obs:
        key = (o["type"] or "").upper()
        if key in (_OEE_AVAILABILITY, _OEE_EXECUTION, _OEE_MODE, _OEE_PROGRAM):
            picks[key] = o
    availability = (picks.get(_OEE_AVAILABILITY, {}).get("value", "") or "").upper()
    execution = (picks.get(_OEE_EXECUTION, {}).get("value", "") or "").upper()
    available = availability == "AVAILABLE"
    active = execution == "ACTIVE"
    verdict = "running" if (available and active) else "available_idle" if available else "down"
    return {
        "endpoint": s(target.name, 64),
        "availability": s(availability, 32),
        "execution": s(execution, 32),
        "controller_mode": s(picks.get(_OEE_MODE, {}).get("value", ""), 32),
        "program": s(picks.get(_OEE_PROGRAM, {}).get("value", ""), 96),
        "available": available,
        "running": active,
        "verdict": verdict,
        "note": "OEE availability/performance inputs from /current. Full OEE % needs "
        "planned production time + ideal cycle time (not exposed by MTConnect).",
    }


# num() is re-exported for callers that want numeric coercion on observation values.
__all__ = [
    "mtconnect_probe",
    "mtconnect_current",
    "mtconnect_sample",
    "mtconnect_assets",
    "mtconnect_oee_snapshot",
    "num",
]
